"""T2.3 acceptance: citation markers map to reference entries both ways."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.ingest import pdfio
from app.ingest.citations import build_citations, expand_marker, marker_numbers
from app.ingest.parser import parse_pdf
from app.ingest.references import extract_references

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "pdf"
V1 = FIXTURES / "1706.03762v1.pdf"
V7 = FIXTURES / "1706.03762v7.pdf"
BERT = FIXTURES / "1810.04805_bert.pdf"
GPT3 = FIXTURES / "2005.14165_gpt3.pdf"


@pytest.fixture(scope="module")
def v1() -> Any:
    return parse_pdf(V1, "doc-cite-v1")


def _citations(model: Any) -> list[Any]:
    return [item for item in model.citations if item.method == "link_annotation"]


def test_every_reference_in_v1_is_cited(v1: Any) -> None:
    """The paper cites all 36 of its references; a gap means a missed marker."""
    assert len(v1.model.references) == 36
    assert v1.citation_coverage.cited == 36
    assert v1.citation_coverage.uncited == 0


def test_no_citation_points_at_a_missing_reference(v1: Any) -> None:
    assert v1.citation_coverage.dangling == 0


def test_marker_text_matches_its_reference_numbers(v1: Any) -> None:
    """Bidirectional check: "[31, 2, 5]" must map to exactly r31, r2 and r5."""
    references = {reference.id: reference for reference in v1.model.references}
    for citation in _citations(v1.model):
        printed = [f"r{number}" for number in marker_numbers(citation.marker)]
        assert sorted(citation.ref_ids) == sorted(printed), citation.marker
        for ref_id in citation.ref_ids:
            assert ref_id in references, f"{citation.marker} points at missing {ref_id}"


def test_ten_markers_spot_check(v1: Any) -> None:
    """Acceptance: ten sampled markers resolve to the right printed entry."""
    references = {reference.id: reference for reference in v1.model.references}
    samples = [item for item in _citations(v1.model) if item.marker.startswith("[")][:10]
    assert len(samples) == 10
    for citation in samples:
        number = int(citation.marker.strip("[]").split(",")[0])
        target = references[citation.ref_ids[0]]
        # The entry's own text starts with its printed number.
        assert target.raw.lstrip().startswith(f"[{number}]"), (
            f"{citation.marker} resolved to {target.raw[:40]!r}"
        )


def test_a_reference_resolves_back_to_the_markers_that_cite_it(v1: Any) -> None:
    """The reverse direction of the same link, which the reader relies on."""
    cited = {ref_id for item in v1.model.citations for ref_id in item.ref_ids}
    for reference in v1.model.references:
        assert reference.id in cited, f"{reference.id} is never cited"


def test_citation_anchor_is_the_block_the_marker_sits_in(v1: Any) -> None:
    """H01: a marker without a block anchor is not evidence."""
    blocks = {block.id: block for block in v1.model.blocks}
    for citation in v1.model.citations:
        block = blocks[citation.block_id]
        assert block.page == _page_of(v1.model, citation)
        assert citation.bbox, "the marker must carry its own bbox"
        x0, y0, x1, y1 = block.bbox
        cx = (citation.bbox[0] + citation.bbox[2]) / 2
        cy = (citation.bbox[1] + citation.bbox[3]) / 2
        assert x0 - 2 <= cx <= x1 + 2 and y0 - 2 <= cy <= y1 + 2


def _page_of(model: Any, citation: Any) -> int:
    return next(block.page for block in model.blocks if block.id == citation.block_id)


def test_link_annotations_are_preferred_over_regex(v1: Any) -> None:
    """Every marker on a page with links must come from the links."""
    methods = {citation.method for citation in v1.model.citations}
    assert methods == {"link_annotation"}
    assert v1.citation_coverage.by_regex == 0


def test_a_marker_split_across_links_is_rejoined(v1: Any) -> None:
    """'[31, 2, 5]' is three links; the marker must not be three citations."""
    markers = [citation.marker for citation in _citations(v1.model)]
    assert "[31, 2, 5]" in markers


def test_reference_entries_are_not_mistaken_for_citations(v1: Any) -> None:
    """A bibliography entry's leading "[7]" is a label, not a citation."""
    reference_blocks = {reference.block_id for reference in v1.model.references}
    for citation in v1.model.citations:
        assert citation.block_id not in reference_blocks


def test_v7_keeps_full_coverage(v1: Any) -> None:
    v7 = parse_pdf(V7, "doc-cite-v7")
    assert len(v7.model.references) == 40
    assert v7.citation_coverage.cited == 40
    assert v7.citation_coverage.dangling == 0
    assert v7.citation_coverage.by_regex == 0


def test_author_year_markers_resolve_through_links() -> None:
    """BERT cites as "(Peters et al., 2018a)" — no number to fall back on."""
    model = parse_pdf(BERT, "doc-cite-bert").model
    assert len(model.references) == 56
    assert any("et al" in citation.marker for citation in model.citations)
    assert all(citation.ref_ids for citation in model.citations)


def test_separate_markers_are_not_merged_across_prose() -> None:
    """GPT-3 writes "... [DCLT18], to 1.5 billion parameters [RWC+19]".

    Merging those two links would produce one citation spanning a sentence and
    a marker far longer than any marker in the paper.
    """
    model = parse_pdf(GPT3, "doc-cite-gpt3-merge").model
    longest = max(len(citation.marker) for citation in model.citations)
    assert longest < 60, f"a marker spans {longest} characters"
    assert not any("billion" in citation.marker for citation in model.citations)


def test_adjacent_links_of_one_marker_still_merge() -> None:
    """The numeric case the merge exists for must keep working."""
    model = parse_pdf(V1, "doc-cite-merge").model
    markers = {citation.marker for citation in model.citations}
    assert "[31, 2, 5]" in markers
    assert "[4, 25, 26, 20]" in markers


def test_alpha_keys_do_not_collapse_the_bibliography() -> None:
    """GPT-3 numbers nothing: 144 entries keyed "[VSP+17]"."""
    model = parse_pdf(GPT3, "doc-cite-gpt3").model
    assert len(model.references) == 144


def test_expand_marker_handles_ranges_and_lists() -> None:
    assert expand_marker("3, 5-7") == [3, 5, 6, 7]
    assert expand_marker("12") == [12]
    assert expand_marker("1,2") == [1, 2]


def test_a_numbered_entry_that_wraps_is_one_reference() -> None:
    """A volume line "9(8):1735-1780" continues the entry above it."""
    model = parse_pdf(V1, "doc-cite-wrap").model
    short = [reference for reference in model.references if len(reference.raw) < 40]
    assert not short, [reference.raw for reference in short]


def test_references_are_extracted_from_the_job_path() -> None:
    """The job must produce the same rows as the sync path (it once did not)."""
    model = parse_pdf(V1, "doc-cite-job").model
    doc = pdfio.open_document(V1)
    try:
        references = extract_references(model.blocks, "doc-cite-job")
        citations, coverage = build_citations(doc, model.blocks, references)
    finally:
        pdfio.close_document(doc)
    assert len(references) == len(model.references)
    assert len(citations) == len(model.citations)
    assert coverage.cited == 36


def test_citation_endpoint_returns_markers_and_coverage() -> None:
    """The contract's endpoint, plus the coverage counters in the stats."""
    import asyncio

    from httpx import ASGITransport, AsyncClient

    from app.db import get_session_factory
    from app.main import create_app
    from app.models.orm import AssetRow, CitationRow, Document, ReferenceRow
    from app.models.orm import Block as BlockRow

    parsed = parse_pdf(V1, "doc-cite-api").model

    async def run() -> tuple[list[Any], dict[str, Any]]:
        factory = get_session_factory()
        async with factory() as session:
            session.add(
                Document(
                    id="doc-cite-api",
                    sha256="sha-cite-api",
                    title=parsed.meta.title,
                    status="ready",
                    file_path=str(V1),
                )
            )
            await session.flush()
            for block in parsed.blocks:
                session.add(
                    BlockRow(
                        doc_id="doc-cite-api",
                        id=block.id,
                        type=block.type,
                        page=block.page,
                        bbox=block.bbox,
                        reading_order=block.reading_order,
                        section_id=block.section_id,
                        text=block.text,
                    )
                )
            for reference in parsed.references:
                session.add(
                    ReferenceRow(
                        id=f"doc-cite-api:{reference.id}",
                        doc_id="doc-cite-api",
                        index=reference.index,
                        raw=reference.raw,
                        block_id=reference.block_id,
                        bbox=reference.bbox,
                    )
                )
            for citation in parsed.citations:
                session.add(
                    CitationRow(
                        id=f"doc-cite-api:{citation.id}",
                        doc_id="doc-cite-api",
                        marker=citation.marker,
                        ref_ids=[f"doc-cite-api:{ref}" for ref in citation.ref_ids],
                        block_id=citation.block_id,
                        bbox=citation.bbox,
                        method=citation.method,
                    )
                )
            for asset in parsed.assets:
                session.add(
                    AssetRow(
                        id=f"doc-cite-api:{asset.id}",
                        doc_id="doc-cite-api",
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
            markers = await client.get("/api/v1/documents/doc-cite-api/citations")
            document = await client.get("/api/v1/documents/doc-cite-api")
        return markers.json(), document.json()

    markers, document = asyncio.run(run())
    assert len(markers) == 58
    assert {marker["method"] for marker in markers} == {"link_annotation"}
    assert all(marker["ref_ids"] and marker["bbox"] for marker in markers)
    stats = document["stats"]
    assert stats["references"] == 36
    assert stats["cited_references"] == 36
    assert stats["uncited_references"] == 0
    assert stats["dangling_citations"] == 0
    # Assets are not blocks: counting block types reported zero of each.
    assert stats["figures"] == 5
    assert stats["tables"] == 4
    assert stats["formulas"] >= 8
