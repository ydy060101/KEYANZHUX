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


def test_a_table_exposes_html_when_the_source_has_structure(model: Any) -> None:
    """T2.6 renders a table's cells; the crop stays the fallback (02 §4.2)."""
    tables = [asset for asset in model.assets if asset.kind == "table"]
    with_html = [asset for asset in tables if asset.html]
    assert with_html, "find_tables should read at least one of this paper's four tables"
    assert all("<td" in asset.html or "<th" in asset.html for asset in with_html if asset.html)
    # The crop is still written for every table, HTML or not: it is what the
    # reader falls back to when the extracted structure is wrong.
    assert all(Path(asset.path).is_file() for asset in tables)


def test_figures_and_formulas_carry_no_table_html(model: Any) -> None:
    others = [asset for asset in model.assets if asset.kind != "table"]
    assert all(asset.html is None for asset in others)


def _block(text: str, page: int = 1, block_id: str = "b1_1") -> Any:
    from app.models.schemas import Block

    return Block(id=block_id, type="caption", page=page, bbox=[0.0, 0.0, 10.0, 10.0], reading_order=1, text=text)


def test_a_caption_without_a_colon_is_still_a_caption() -> None:
    """A textbook sets "Figure 1.1 Machine learning is an area of…".

    The 541-page book prints 290 captions this way and not one colon, so a
    pattern that requires punctuation found no figure or table at all for it
    and the reader's two lists came up empty.
    """
    captions = find_captions(
        [
            _block("Figure 1.1 Machine learning is an area of artificial intelligence."),
            _block("Table 2.1 Results on the development set.", block_id="b1_2"),
        ]
    )
    assert [(caption.kind, caption.label) for caption in captions] == [("figure", "1.1"), ("table", "2.1")]


def test_a_sentence_naming_a_figure_is_not_a_caption() -> None:
    """Without punctuation, the capital is what separates the two.

    The book prints both on facing pages: "Figure 1.1 Machine learning…" is
    the caption, "Figure 1.2 depicts several regression problems" is prose.
    """
    captions = find_captions(
        [
            _block("Figure 1.2 depicts several regression and classification problems."),
            _block("Figure 1.2 Regression and classification problems.", block_id="b1_2"),
        ]
    )
    assert [caption.text for caption in captions] == ["Regression and classification problems."]


def test_the_detected_table_must_sit_inside_the_crop(model: Any) -> None:
    """The `text` strategy returns one box spanning the whole page.

    It overlaps every region on that page, so an overlap test accepted it for
    each table in turn and the reader was handed the page's body text as the
    table's cells. A table that is bigger than its crop is a different object.
    """
    from app.ingest.assets import _inside_score

    crop = (72.0, 251.0, 526.0, 519.0)
    assert _inside_score((72.0, 240.0, 526.0, 530.0), crop) is not None
    assert _inside_score((72.0, 66.0, 526.0, 765.0), crop) is None, "the whole page is not this table"
    assert _inside_score((540.0, 251.0, 580.0, 300.0), crop) is None, "another column is not this table"


def test_every_table_strategy_is_tried(model: Any) -> None:
    """A ruled table needs `lines_strict`; a borderless one is only `text`."""
    tables = [asset for asset in model.assets if asset.kind == "table"]
    assert any(asset.html for asset in tables), "the paper's bordered tables should be read as HTML"
