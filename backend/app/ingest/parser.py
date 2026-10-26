"""PDF parsing pipeline — stages 1-3, 5-8 of 01 §7.

Stage order (each independently re-runnable):
  1 ingest check → 2 page probe → 3 layout → 4 OCR (elsewhere) →
  5 metadata → 6 heading tree → 7 figures/tables/formulas → 8 references
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..models.schemas import (
    Asset,
    Block,
    BlockType,
    Citation,
    DocMeta,
    DocumentModel,
    OutlineItem,
    Reference,
    SourceKind,
)
from . import pdfio

ARXIV_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")
CITE_RE = re.compile(r"\[(\d+(?:\s*[,\-–]\s*\d+)*)\]")
_HEADING_RE = re.compile(r"^(\d+(?:\.\d+){0,2})\.?\s+(\S.{0,120})$")
_REF_START = re.compile(r"^\[?(\d+)\]?[\.\s]")
# A reference list ends at the first appendix-like heading.
_REF_STOP = re.compile(
    r"^(appendix|attention visualizations|supplementary|acknowledg)", re.IGNORECASE
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


def _looks_two_column(page: pdfio.Page) -> bool:
    """A crude but stable signal: text blocks clustered on both halves."""
    width, _ = pdfio.page_size(page)
    left = right = 0
    for x0, _, x1, _, _ in pdfio.page_blocks(page):
        if x1 < width * 0.5:
            left += 1
        elif x0 > width * 0.5:
            right += 1
    return left >= 3 and right >= 3


def reading_order(page: pdfio.Page) -> list[pdfio.RawBlock]:
    """Return blocks in column-major reading order (left column first)."""
    width, _ = pdfio.page_size(page)
    blocks = pdfio.page_blocks(page)
    if not _looks_two_column(page):
        return sorted(blocks, key=lambda b: (round(b[1], 1), b[0]))
    left = [b for b in blocks if (b[0] + b[2]) / 2 < width / 2]
    right = [b for b in blocks if (b[0] + b[2]) / 2 >= width / 2]
    return sorted(left, key=lambda b: (round(b[1], 1), b[0])) + sorted(
        right, key=lambda b: (round(b[1], 1), b[0])
    )


def _block_type(text: str, bbox: tuple[float, float, float, float], page_height: float) -> BlockType:
    stripped = text.strip()
    if _HEADING_RE.match(stripped) and len(stripped) < 90:
        return "heading"
    if stripped.startswith(("[", "1.", "2.")) and re.match(r"^\[?\d+\]?\s", stripped):
        return "reference"
    if stripped.lower().startswith(("figure", "table", "fig.")):
        return "caption"
    return "paragraph"


def extract_blocks(
    doc: pdfio.Document, pages: list[PageStats], doc_id: str, page_limit: int | None = None
) -> tuple[list[Block], list[OutlineItem]]:
    blocks: list[Block] = []
    outline: list[OutlineItem] = []
    counter = 0
    section = "s0"
    total = pdfio.page_count(doc)
    limit = min(page_limit or total, total)

    for page_index in range(limit):
        page = pdfio.page(doc, page_index)
        _, page_height = pdfio.page_size(page)
        for x0, y0, x1, y1, text in reading_order(page):
            counter += 1
            block_id = f"b{counter}"
            kind = _block_type(text, (x0, y0, x1, y1), page_height)
            if kind == "heading":
                match = _HEADING_RE.match(" ".join(text.split()))
                level = 1 if match and "." not in (match.group(1) or "") else 2
                section = f"s{counter}"
                outline.append(
                    OutlineItem(
                        id=section,
                        level=level,
                        title=" ".join(text.split())[:200],
                        page=page_index + 1,
                        block_id=block_id,
                    )
                )
            blocks.append(
                Block(
                    id=block_id,
                    type=kind,
                    page=page_index + 1,
                    bbox=[x0, y0, x1, y1],
                    reading_order=counter,
                    section_id=section,
                    text=text.strip(),
                    confidence=1.0,
                )
            )
    return blocks, outline


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


def extract_references(blocks: list[Block], doc_id: str) -> tuple[list[Reference], list[Citation]]:
    """Collect numbered reference entries and every in-text citation marker.

    Reference entries wrap across PDF blocks, so a block that does not start
    with a number is appended to the previous entry rather than becoming one.
    """
    references: list[Reference] = []
    citations: list[Citation] = []
    refs_started = False

    for block in blocks:
        text = block.text.strip()
        lowered = text.lower()

        if not refs_started:
            if lowered.startswith("references") and len(text) < 40:
                refs_started = True
                continue
        else:
            if _REF_STOP.match(text) and len(text) < 80:
                refs_started = False
            else:
                start = _REF_START.match(text)
                if start:
                    index = int(start.group(1))
                    references.append(
                        Reference(
                            id=f"r{index}",
                            index=index,
                            raw=text,
                            block_id=block.id,
                            bbox=block.bbox,
                        )
                    )
                elif references:
                    previous = references[-1]
                    previous.raw = f"{previous.raw} {text}".strip()

        for marker in CITE_RE.finditer(text):
            numbers = _expand_marker(marker.group(1))
            citations.append(
                Citation(
                    id=f"c{len(citations) + 1}",
                    marker=marker.group(0),
                    ref_ids=[f"r{n}" for n in numbers],
                    block_id=block.id,
                    bbox=block.bbox,
                    method="regex",
                )
            )
    return references, citations


def _expand_marker(spec: str) -> list[int]:
    numbers: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if re.match(r"^\d+\s*[-–]\s*\d+$", part):
            start, end = re.split(r"\s*[-–]\s*", part)
            low, high = int(start or 0), int(end or 0)
            if 0 < high - low <= 50:
                numbers.extend(range(low, high + 1))
        elif part.isdigit():
            numbers.append(int(part))
    return numbers


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
        blocks, outline = extract_blocks(doc, pages, doc_id, page_limit=page_limit)
        meta = extract_meta(doc, blocks, doc_id)
        first_text = blocks[0].text if blocks else ""
        arxiv_id, version = detect_arxiv_id(path.name, first_text)
        references, citations = extract_references(blocks, doc_id)
        assets: list[Asset] = []

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
        return ParseResult(model=model, page_stats=pages)
    finally:
        pdfio.close_document(doc)
