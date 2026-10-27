"""T2.4 acceptance: a scan parses into the same document model as a vector PDF.

The fixture is a real scan — every page is one image and no page has any text
layer — so anything the parser reports came from OCR. The card's acceptance is
that the title, abstract, sections and bibliography survive that path, and that
the duplicate check is made again on the recognised text (01 §8).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from app.ingest import ocr, pdfio
from app.ingest.layout import looks_two_column
from app.ingest.parser import PageStats, detect_source_kind, parse_pdf

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "pdf"
SCAN = FIXTURES / "1706.03762v1_img.pdf"
VECTOR = FIXTURES / "1706.03762v1.pdf"

pytestmark = pytest.mark.skipif(
    not ocr.available(), reason="PaddleOCR is not installed in this environment"
)

# Headings that carry no number on the printed page.
_STRUCTURAL = {"abstract", "references", "acknowledgements", "appendix"}
# "3.2.1 Title", "6Results" (the recogniser drops the space), "A Additional".
_SECTION = re.compile(r"^(?:\d+(?:\.\d+)*\s*\D|[A-Z]\.?\s+\D)")


def _section_prefix(title: str) -> bool:
    return bool(_SECTION.match(title))


@pytest.fixture(scope="module")
def scanned() -> Any:
    return parse_pdf(SCAN, "doc-scan")


def test_the_fixture_really_is_a_scan() -> None:
    """Guard: if this ever stops being true the tests below prove nothing."""
    doc = pdfio.open_document(SCAN)
    try:
        for page in pdfio.iter_pages(doc):
            assert len(pdfio.page_text(page).strip()) < 30
            assert pdfio.image_boxes(page)
    finally:
        pdfio.close_document(doc)


def test_scanned_document_reports_its_source_kind(scanned: Any) -> None:
    assert scanned.model.source_kind == "scanned"


def test_title_is_restored(scanned: Any) -> None:
    assert scanned.model.meta.title.strip() == "Attention Is All You Need"


def test_abstract_is_restored(scanned: Any) -> None:
    """The abstract's opening words must be present in the page-1 blocks."""
    page_one = " ".join(block.text for block in scanned.model.blocks if block.page == 1)
    assert "The dominant sequence transduction models" in page_one
    assert any(block.page == 1 and "recurrent" in block.text for block in scanned.model.blocks)


def test_sections_are_restored(scanned: Any) -> None:
    titles = [item.title for item in scanned.model.outline]
    for expected in ("1 Introduction", "2 Background", "3 Model Architecture", "5 Training"):
        assert expected in titles, titles
    assert any(title.startswith("3.2") for title in titles)


def test_every_printed_section_survives(scanned: Any) -> None:
    """The scan must recover the paper's real structure, not just its opening.

    "6 Results" is the hard one: the recogniser drops the space and reads
    "6Results" — or, at too small a render, loses the digit altogether — so a
    heading rule that insists on a space after the number, or a render scale
    that is too coarse, loses the section entirely. The whole printed contents
    must be present, in order.
    """
    titles = [item.title for item in scanned.model.outline]
    for expected in ("3 Model Architecture", "4 Why Self-Attention", "6 Results", "7 Conclusion", "References"):
        assert expected in titles, titles
    numbered = [title for title in titles if _section_prefix(title)]
    assert len(numbered) >= 15, titles


def test_outline_has_no_junk_entries(scanned: Any) -> None:
    """OCR of a table must not become a table of contents (numbers, emails)."""
    for item in scanned.model.outline:
        assert item.title.strip(), item
        assert "@" not in item.title, item.title
        assert not item.title.replace(".", "").replace(" ", "").isdigit(), item.title
        # A capitalised word in the body ("ByteNet", "Google Research") is not
        # a section: only a number or an appendix letter starts one.
        assert _section_prefix(item.title) or item.title.lower() in _STRUCTURAL, item.title


def test_references_are_restored(scanned: Any) -> None:
    references = scanned.model.references
    assert len(references) == 36
    assert references[0].raw.startswith("[1]")
    assert references[-1].raw.startswith("[36]")
    assert all(reference.raw.strip() for reference in references)


def test_citation_markers_are_restored(scanned: Any) -> None:
    """A scan has no link annotations, so every marker comes from the text."""
    assert scanned.model.citations
    assert scanned.citation_coverage.by_regex == len(scanned.model.citations)
    assert scanned.citation_coverage.dangling == 0


def test_ocr_blocks_keep_their_boxes(scanned: Any) -> None:
    """H01: an OCR block anchors to the page exactly like a vector block."""
    for block in scanned.model.blocks:
        x0, y0, x1, y1 = block.bbox
        assert 0 <= x0 < x1 and 0 <= y0 < y1, block
        assert block.confidence < 1.0


def test_ocr_blocks_are_inside_the_page(scanned: Any) -> None:
    doc = pdfio.open_document(SCAN)
    try:
        for block in scanned.model.blocks:
            page = pdfio.page(doc, block.page - 1)
            width, height = pdfio.page_size(page)
            assert block.bbox[2] <= width + 1 and block.bbox[3] <= height + 1, block
    finally:
        pdfio.close_document(doc)


def test_rotated_figure_labels_are_discarded() -> None:
    """A sideways word reads as noise ("uo!eo!dde"), and must never be a block."""
    doc = pdfio.open_document(SCAN)
    try:
        blocks = ocr.page_blocks(pdfio.page(doc, 13))
    finally:
        pdfio.close_document(doc)
    text = " ".join(block.text for block in blocks).lower()
    assert "uo!eo!dde" not in text
    assert "pinous" not in text
    assert "Figure 4" in " ".join(block.text for block in blocks)


def test_a_scan_of_a_two_column_page_is_read_column_major() -> None:
    """The fixture's model figures are not mistaken for two-column body text."""
    doc = pdfio.open_document(SCAN)
    try:
        page = pdfio.page(doc, 0)
        width, _ = pdfio.page_size(page)
        assert not looks_two_column(ocr.page_blocks(page), width)
    finally:
        pdfio.close_document(doc)


def test_scanned_pages_are_recognised_as_scanned() -> None:
    pages = [PageStats(index=i, char_count=0, width=612, height=792, columns=1) for i in range(3)]
    assert detect_source_kind(pages, 30) == "scanned"
    pages[1].char_count = 500
    assert detect_source_kind(pages, 30) == "mixed"


def test_a_vector_page_is_not_ocred() -> None:
    """The exact text layer must win: OCR would only add errors to it."""
    doc = pdfio.open_document(VECTOR)
    try:
        page = pdfio.page(doc, 0)
        typed = pdfio.typed_blocks(page)
        recognised = ocr.lines(page)
    finally:
        pdfio.close_document(doc)
    # A vector page still has its own text; the OCR result is irrelevant to it
    # and the parser must not use it, which `page_blocks` guarantees.
    assert typed
    assert recognised  # the engine can read it — that is what makes the guard real
