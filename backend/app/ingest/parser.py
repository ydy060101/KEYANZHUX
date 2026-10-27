"""PDF parsing pipeline — stages 1-3, 5-8 of 01 §7.

Stage order (each independently re-runnable):
  1 ingest check → 2 page probe → 3 layout → 4 OCR (elsewhere) →
  5 metadata → 6 heading tree → 7 figures/tables/formulas → 8 references
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..models.schemas import (
    Block,
    BlockType,
    DocMeta,
    DocumentModel,
    OutlineItem,
    Reference,
    SourceKind,
)
from . import layout, ocr, pdfio
from .assets import extract_assets
from .citations import Coverage, build_citations
from .outline import build_outline
from .references import extract_references as _extract_references

logger = logging.getLogger(__name__)

ARXIV_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")
_HEADING_RE = re.compile(r"^(\d+(?:\.\d+){0,2})\.?\s+(\S.{0,120})$")
# A bibliography entry: a bracketed label ("[3] Denny" / "[3]Denny" /
# "[VSP+17] Ashish") or a dotted number ("3. Denny" / "3.Denny"). The label is
# required — a paragraph that merely opens with a number ("12 million people")
# is not an entry — and the lookahead needs a letter, so "3." alone is not one.
_REFERENCE_RE = re.compile(
    r"^(?:\[(?:\d{1,3}|[A-Za-z][\w+:.-]*\d)\]\s*|\d{1,3}\.\s*)(?=[^\W\d_])", re.UNICODE
)


@dataclass
class PageStats:
    index: int
    char_count: int
    width: float
    height: float
    columns: int


@dataclass
class FontProfile:
    """Dominant body size and the largest text on page 1 — enough to tell a
    title from a heading from a paragraph without knowing the paper."""

    body_size: float
    max_size: float
    size_by_block: dict[int, float]


def font_profile(doc: pdfio.Document, page_index: int = 0) -> FontProfile:
    page = pdfio.page(doc, page_index)
    weights: dict[float, int] = {}
    blocks: dict[int, float] = {}
    for block_no, block in enumerate(pdfio.page_dict(page).get("blocks", [])):
        sizes: list[float] = []
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                size = round(float(span["size"]), 1)
                if str(span["text"]).strip():
                    sizes.append(size)
                    weights[size] = weights.get(size, 0) + len(str(span["text"]))
        if sizes:
            blocks[block_no] = max(sizes)
    body = max(weights, key=lambda size: weights[size]) if weights else 10.0
    largest = max(weights) if weights else body
    return FontProfile(body_size=body, max_size=largest, size_by_block=blocks)


@dataclass
class ParseResult:
    model: DocumentModel
    page_stats: list[PageStats] = field(default_factory=list)
    citation_coverage: Coverage = field(default_factory=Coverage)


def detect_source_kind(pages: list[PageStats], threshold: int) -> SourceKind:
    scanned = sum(1 for page in pages if page.char_count < threshold)
    if scanned == 0:
        return "vector"
    if scanned == len(pages):
        return "scanned"
    return "mixed"


def probe_pages(doc: pdfio.Document, threshold: int) -> list[PageStats]:
    stats: list[PageStats] = []
    for index, page in enumerate(pdfio.iter_pages(doc)):
        text = pdfio.page_text(page)
        width, height = pdfio.page_size(page)
        stats.append(
            PageStats(
                index=index + 1,
                char_count=len(text.strip()),
                width=width,
                height=height,
                columns=2 if _looks_two_column(page) else 1,
            )
        )
    return stats


def _looks_two_column(page: pdfio.Page, blocks: list[pdfio.TypedBlock] | None = None) -> bool:
    width, _ = pdfio.page_size(page)
    return layout.looks_two_column(blocks if blocks is not None else pdfio.typed_blocks(page), width)


def reading_order(page: pdfio.Page) -> list[pdfio.TypedBlock]:
    """Return a page's text blocks in reading order (see `layout.order`)."""
    width, _ = pdfio.page_size(page)
    return layout.order(pdfio.typed_blocks(page), width)


def page_blocks(page: pdfio.Page, *, scanned: bool) -> list[pdfio.TypedBlock]:
    """A page's blocks in reading order, from the text layer or from OCR.

    Only a page with no usable text layer is OCR'd (T2.4): the PDF's own text
    is exact and carries font sizes and bboxes that no recogniser can match,
    so it is always preferred where it exists. A `mixed` document therefore
    uses both paths, page by page.
    """
    width, _ = pdfio.page_size(page)
    if scanned:
        return layout.order(ocr.page_blocks(page), width)
    return reading_order(page)


def _block_type(text: str) -> BlockType:
    stripped = text.strip()
    if _HEADING_RE.match(stripped) and len(stripped) < 90:
        return "heading"
    # "[3] Denny Britz" and "[3]Denny Britz" are the same entry: the source PDF
    # sets no space after the bracket, so requiring one would type the vector
    # copy's whole bibliography as paragraphs while the OCR copy types it as
    # references — the two parses of one paper would then disagree.
    if _REFERENCE_RE.match(stripped):
        return "reference"
    if stripped.lower().startswith(("figure", "table", "fig.")):
        return "caption"
    return "paragraph"


def _is_scanned(stats: PageStats, threshold: int) -> bool:
    return stats.char_count < threshold


def extract_blocks(
    doc: pdfio.Document,
    pages: list[PageStats],
    doc_id: str,
    page_limit: int | None = None,
    *,
    threshold: int = 30,
) -> tuple[list[Block], list[OutlineItem]]:
    """Every block in the document, with its heading tree.

    Blocks are identified by page (`b12_3`), not by a running counter: a
    windowed parse (T2.5) resumes from any page, and an id that depends on how
    many blocks came before it would name a different block after a resume.
    """
    scanned = {page.index: _is_scanned(page, threshold) for page in pages}
    blocks: list[Block] = []
    sizes: dict[str, float] = {}
    total = pdfio.page_count(doc)
    limit = min(page_limit or total, total)

    for page_index in range(limit):
        page = pdfio.page(doc, page_index)
        raw_blocks = page_blocks(page, scanned=scanned.get(page_index + 1, False))
        typed = to_model_blocks(
            raw_blocks,
            page_no=page_index + 1,
            scanned=scanned.get(page_index + 1, False),
            start_order=len(blocks) + 1,
        )
        for block, raw in zip(typed, raw_blocks, strict=True):
            sizes[block.id] = raw.size
        blocks.extend(typed)

    # Stage 6 (T2.1): the heading tree replaces the block-level guess above,
    # so sections come from the PDF outline when it has one.
    outline = build_outline(doc, blocks, body_size=_body_size(doc, blocks, scanned), sizes=sizes)
    return blocks, outline


def to_model_blocks(
    raw_blocks: list[pdfio.TypedBlock],
    *,
    page_no: int,
    scanned: bool,
    start_order: int,
) -> list[Block]:
    """One page's extracted blocks as document-model blocks.

    Ids are page-scoped so a window can be parsed, persisted and later resumed
    without knowing how many blocks preceded it. `reading_order` is passed in
    because that ordering *is* document-wide and the caller owns it.
    """
    blocks: list[Block] = []
    for index, raw in enumerate(raw_blocks, start=1):
        block_id = f"b{page_no}_{index}"
        blocks.append(
            Block(
                id=block_id,
                type=_block_type(raw.text),
                page=page_no,
                bbox=[raw.x0, raw.y0, raw.x1, raw.y1],
                reading_order=start_order + index - 1,
                # Sections come from the heading tree; until then a block
                # belongs to the document's opening section.
                section_id="s0",
                text=raw.text.strip(),
                # A recognised character is a guess; leaving 1.0 would claim
                # the same certainty as extracted text (H01).
                confidence=0.9 if scanned else 1.0,
                bold=raw.bold,
            )
        )
    return blocks


def _body_size(doc: pdfio.Document, blocks: list[Block] | None = None, scanned: dict[int, bool] | None = None) -> float:
    """The dominant body size, from the font profile or from OCR line heights.

    A scanned page has no spans to profile, so its body size comes from the
    median block size instead — without it every heading test compares against
    a meaningless default of 10pt.
    """
    try:
        if not scanned or not all(scanned.values()):
            return font_profile(doc).body_size
    except Exception:  # pragma: no cover - malformed page 1
        logger.warning("font profile unavailable, assuming 10pt body")
        return 10.0
    sizes = sorted(block_height for block in (blocks or []) for block_height in [block.bbox[3] - block.bbox[1]])
    if not sizes:
        return 10.0
    return sizes[len(sizes) // 2]


def _is_author_line(text: str) -> bool:
    """A name line: mostly capitalised words, no email, no long sentence."""
    line = " ".join(text.split())
    if not line or len(line) > 120 or "@" in line:
        return False
    if line.lower().startswith(("abstract", "arxiv", "keywords")):
        return False
    words = [w for w in line.split() if w]
    if not 1 <= len(words) <= 12:
        return False
    # A sentence ends with a period and has many lowercase words.
    return not (line.endswith(".") and sum(1 for w in words if w[:1].islower()) > 3)


def _affiliation_near(blocks: list[Block], index: int) -> str | None:
    """The line under a name block usually holds the affiliation."""
    if index + 1 >= len(blocks):
        return None
    following = blocks[index + 1]
    if following.page != 1 or following.bbox[1] < blocks[index].bbox[3]:
        return None
    first_line = following.text.split("\n")[0].strip()
    if not first_line or "@" in first_line or len(first_line) > 80:
        return None
    return first_line


def extract_meta(doc: pdfio.Document, blocks: list[Block], doc_id: str) -> DocMeta:
    """Synchronous rule-based extraction.

    The async pipeline replaces this with `metadata.extract_meta_llm`, which
    keeps these results as its fallback.
    """
    from .metadata import rule_based_meta

    return rule_based_meta(doc, blocks, doc_id)


def extract_references(blocks: list[Block], doc_id: str) -> list[Reference]:
    """The bibliography entries, in reading order (see `references.py`)."""
    return _extract_references(blocks, doc_id)


def detect_arxiv_id(filename: str, first_page_text: str) -> tuple[str | None, str | None]:
    for source in (filename, first_page_text[:2000]):
        match = ARXIV_RE.search(source)
        if match:
            return match.group(1), match.group(2)
    return None, None


def parse_pdf(path: Path, doc_id: str, *, threshold: int = 30, page_limit: int | None = None) -> ParseResult:
    doc = pdfio.open_document(path)
    try:
        pages = probe_pages(doc, threshold)
        blocks, outline = extract_blocks(doc, pages, doc_id, page_limit=page_limit, threshold=threshold)
        meta = extract_meta(doc, blocks, doc_id)
        first_text = blocks[0].text if blocks else ""
        arxiv_id, version = detect_arxiv_id(path.name, first_text)
        references = extract_references(blocks, doc_id)
        citations, coverage = build_citations(doc, blocks, references, page_limit=page_limit)
        assets = extract_assets(doc, blocks, doc_id)

        model = DocumentModel(
            doc_id=doc_id,
            sha256="",
            arxiv_id=arxiv_id,
            version=version,
            page_count=pdfio.page_count(doc),
            source_kind=detect_source_kind(pages, threshold),
            meta=meta,
            outline=outline,
            blocks=blocks,
            references=references,
            citations=citations,
            assets=assets,
        )
        return ParseResult(model=model, page_stats=pages, citation_coverage=coverage)
    finally:
        pdfio.close_document(doc)
