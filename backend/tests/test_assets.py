"""T2.2 acceptance: figures, tables and formulas are cropped and served."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.ingest import pdfio
from app.ingest.assets import find_captions
from app.ingest.parser import parse_pdf

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "pdf"
V1 = FIXTURES / "1706.03762v1.pdf"


@pytest.fixture(scope="module")
def model() -> Any:
    return parse_pdf(V1, "doc-assets").model


def test_v1_has_the_five_figures_the_paper_prints(model: Any) -> None:
    figures = [asset for asset in model.assets if asset.kind == "figure"]
    assert len(figures) == 5, [asset.id for asset in figures]


def test_v1_has_the_four_tables_the_paper_prints(model: Any) -> None:
    tables = [asset for asset in model.assets if asset.kind == "table"]
    assert len(tables) == 4, [asset.id for asset in tables]


def test_captions_are_paired_with_their_numbers(model: Any) -> None:
    captions = find_captions(model.blocks)
    numbers = {(caption.kind, caption.number) for caption in captions}
    assert ("figure", 1) in numbers
    assert ("table", 1) in numbers
    assert ("table", 2) in numbers


def test_a_sentence_starting_with_table_is_not_a_caption(model: Any) -> None:
    """Table 2 summarizes our results" is body text, not a caption."""
    captions = find_captions(model.blocks)
    texts = [caption.text for caption in captions]
    assert not any(text.startswith("summarizes") for text in texts)


def test_every_asset_crop_exists_and_is_a_png(model: Any, tmp_path: Path) -> None:
    for asset in model.assets:
        path = Path(asset.path)
        assert path.is_file(), f"{asset.id} has no crop"
        head = path.read_bytes()[:8]
        assert head == b"\x89PNG\r\n\x1a\n", f"{asset.id} is not a PNG"


def test_figure_crop_covers_its_caption(model: Any) -> None:
    """The crop must include the caption text, so the reader can trust it."""
    figure = next(asset for asset in model.assets if asset.id == "f1")
    caption = next(
        block for block in model.blocks if block.text.strip().startswith("Figure 1:")
    )
    assert figure.bbox[1] <= caption.bbox[1]
    assert figure.bbox[3] >= caption.bbox[3]


def test_table_crop_extends_below_its_caption(model: Any) -> None:
    """A table's rows are text, so the crop must reach past the caption."""
    table = next(asset for asset in model.assets if asset.id == "t1")
    caption = next(
        block for block in model.blocks if block.text.strip().startswith("Table 1:")
    )
    assert table.bbox[3] > caption.bbox[3] + 50, "the table body was not captured"


def test_formulas_are_found_and_do_not_duplicate_ids(model: Any) -> None:
    formulas = [asset for asset in model.assets if asset.kind == "formula"]
    assert len(formulas) >= 8
    ids = [asset.id for asset in model.assets]
    assert len(ids) == len(set(ids)), "asset ids must be unique"


def test_sub_figure_captions_keep_their_own_ids() -> None:
    """GPT-3 prints Figure 3.1, 3.2, ...; each must survive as its own asset."""
    gpt3 = FIXTURES / "2005.14165_gpt3.pdf"
    parsed = parse_pdf(gpt3, "doc-assets-gpt3").model
    ids = [asset.id for asset in parsed.assets]
    assert len(ids) == len(set(ids)), "a sub-figure collided with its parent"
    figures = {asset.id for asset in parsed.assets if asset.kind == "figure"}
    assert {"f3.1", "f3.2"} <= figures


def test_table_header_is_not_mistaken_for_a_formula(model: Any) -> None:
    formulas = [asset for asset in model.assets if asset.kind == "formula"]
    table_ids = {asset.id for asset in model.assets if asset.kind == "table"}
    assert not table_ids & {asset.id for asset in formulas}


def test_asset_endpoint_serves_png_bytes(tmp_path: Path) -> None:
    """The crop must be downloadable through the contract's endpoint."""
    import asyncio

    from app.api import documents as documents_api
    from app.main import create_app
    from app.models.orm import AssetRow, Document

    async def run() -> tuple[int, bytes, str]:
        from app.db import get_session_factory

        factory = get_session_factory()
        doc = pdfio.open_document(V1)
        try:
            parsed = parse_pdf(V1, "doc-api").model
        finally:
            pdfio.close_document(doc)
        async with factory() as session:
            session.add(
                Document(
                    id="doc-api",
                    sha256="sha-api",
                    title=parsed.meta.title,
                    status="ready",
                    file_path=str(V1),
                )
            )
            await session.flush()
            for asset in parsed.assets:
                session.add(
                    AssetRow(
                        id=f"doc-api:{asset.id}",
                        doc_id="doc-api",
                        kind=asset.kind,
                        page=asset.page,
                        bbox=asset.bbox,
                        path=asset.path,
                    )
                )
            await session.commit()

        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/documents/doc-api/assets/f1")
        return response.status_code, response.content[:8], response.headers.get("content-type", "")

    status, head, media = asyncio.run(run())
    assert status == 200, documents_api.__name__
    assert head == b"\x89PNG\r\n\x1a\n"
    assert media.startswith("image/png")
