"""The bibliography (stage 8, T2.3).

Three layouts occur in the fixtures and all three have to survive:

  * numbered entries      "[3] Denny Britz, ..."            (Transformer)
  * alpha-keyed entries   "[VSP+17] Ashish Vaswani, ..."    (GPT-3)
  * unnumbered entries    "Alan Akbik, Duncan Blythe, ..."  (BERT)

Only the first two can be recognised from the text of an entry. The third is
split by geometry: entries start at the column's left margin and their
continuation lines are indented, so the margin itself is the delimiter. Guessing
from the first word fails — "Guo, and Llion Jones." is a continuation that
begins with a surname.

The raw text is always kept verbatim, so a wrong boundary never invents
bibliographic data (H02).
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from itertools import groupby

from ..models.schemas import Block, Reference

logger = logging.getLogger(__name__)

# A heading that is only the word "References" (any capitalisation).
_HEADING = re.compile(r"^(?:\d+\.?\s*)?(references|bibliography|works cited)$", re.IGNORECASE)
# A reference list ends at the first appendix-like heading. The index is in
# this list because a book's back matter puts it straight after the
# bibliography, and its entries ("Xavier initialization, 113") look enough like
# author-year references to be absorbed as hundreds of fake ones.
_STOP = re.compile(
    r"^(?:[\divxlc]+\s+)?(appendix|attention visualizations|supplementary|acknowledg|index|glossary)",
    re.IGNORECASE,
)
# "[3]" or "3." at the start of an entry. The lookahead requires a letter, which
# a volume number ("9(8):1735") does not have.
_NUMBERED = re.compile(r"^\[?(\d{1,3})\]?[\.\s]?\s*(?=[^\W\d_])", re.UNICODE)
# "[VSP+17]" — a citation key, optionally with a disambiguating suffix.
_KEYED = re.compile(r"^\[([A-Za-z][\w+:.-]*\d[\w+:.-]*)\]\s*")
# "9(8):1735-1780, 1997." continues the entry above: a volume, not an entry.
_JOURNAL_LINE = re.compile(r"^\d+\s*\(?\d*\)?\s*[:.]")
# Continuation lines are indented by this much past the entry's left edge.
_MARGIN_TOLERANCE = 6.0
# A block wider than this fraction of the text block spans the page rather than
# sitting in one of its columns (a running head, a full-width rule).
_SPAN_RATIO = 0.75


def extract_references(blocks: list[Block], doc_id: str) -> list[Reference]:
    """Every bibliography entry, with the block and bbox it was read from."""
    entries = _bibliography_blocks(blocks)
    if not entries:
        logger.info("no bibliography found in %s", doc_id)
        return []
    if _NUMBERED.match(entries[0].text.strip()):
        return _by_label(entries, _NUMBERED, keyed=False)
    if _KEYED.match(entries[0].text.strip()):
        return _by_label(entries, _KEYED, keyed=True)
    return _by_margin(entries)


def _bibliography_blocks(blocks: list[Block]) -> list[Block]:
    """The blocks between the "References" heading and the appendix, if any."""
    start = None
    for index, block in enumerate(blocks):
        text = " ".join(block.text.split())
        if _HEADING.match(text) and len(text) < 40:
            start = index + 1
            break
    if start is None:
        return []

    out: list[Block] = []
    for block in blocks[start:]:
        text = block.text.strip()
        if _STOP.match(text) and len(text) < 80:
            break
        if text:
            out.append(block)
    return out


def _by_label(entries: list[Block], pattern: re.Pattern[str], *, keyed: bool) -> list[Reference]:
    """Split a labelled list, appending unlabelled blocks to the entry above."""
    references: list[Reference] = []
    for block in entries:
        text = block.text.strip()
        match = pattern.match(text)
        if match and not _JOURNAL_LINE.match(text):
            index = len(references) + 1
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
        elif not keyed:
            # Text before the first label is a preamble line, not an entry.
            continue
    return references


def _by_margin(entries: list[Block]) -> list[Reference]:
    """Split an unnumbered list by the left margin each entry starts at.

    The margin is computed *per page*. In a book the text block shifts
    between verso and recto pages: here the even pages sit 39pt further right
    than the odd ones, so a single book-wide margin makes every even-page
    entry look indented and the whole page gets appended to the entry above it
    (605 entries instead of ~1300, one of them 4661 characters long).

    A page may also run two columns, each with its own margin, so the columns
    are found per page as well. Comparing against one global minimum would
    make every right-column block look like a continuation.

    Within a page, blocks are walked column by column, top to bottom: reading
    order interleaves the columns, and appending "the previous reference"
    across that interleaving glues a left-column continuation onto the right
    column's entry.
    """
    references: list[Reference] = []
    ordered_pages = sorted(entries, key=lambda block: block.page)
    for _, page_group in groupby(ordered_pages, key=lambda block: block.page):
        page_blocks = list(page_group)
        columns, limit = _page_layout(page_blocks)
        ordered: list[tuple[int, float, Block]] = []
        for block in page_blocks:
            column = _column_of(block, columns, limit)
            if column is not None:
                ordered.append((column, block.bbox[1], block))
        ordered.sort(key=lambda item: item[:2])

        for column, _, block in ordered:
            margin = columns[column][0]
            if not references or block.bbox[0] <= margin + _MARGIN_TOLERANCE:
                index = len(references) + 1
                references.append(
                    Reference(
                        id=f"r{index}",
                        index=index,
                        raw=block.text.strip(),
                        block_id=block.id,
                        bbox=block.bbox,
                    )
                )
            else:
                previous = references[-1]
                previous.raw = f"{previous.raw} {block.text.strip()}".strip()
    return references


def _column_of(
    block: Block, columns: list[tuple[float, float]], limit: float | None = None
) -> int | None:
    """The column a block sits in, or None if it spans the page.

    A running head ("Bibliography 465") and a centred footer start left of
    the right column and end right of the left one: they belong to no column,
    and taking the nearest one would let each of them start a bogus entry —
    three per page, which is how 376 real entries became 704.

    A single-column list has no gutter to straddle, so every block belongs to
    it (a ragged right edge would otherwise drop the short lines) — but a
    page-wide span is still page furniture, not an entry.
    """
    if limit is not None and block.bbox[2] - block.bbox[0] > limit:
        return None
    if len(columns) == 1:
        return 0
    for index, (left, right) in enumerate(columns):
        if (
            block.bbox[0] >= left - _MARGIN_TOLERANCE
            and block.bbox[2] <= right + _MARGIN_TOLERANCE
        ):
            return index
    return None


def _page_layout(entries: list[Block]) -> tuple[list[tuple[float, float]], float | None]:
    """The page's columns and the width at which a block counts as page-wide.

    Both are decided from the *unfiltered* blocks. Deciding the width from the
    filtered ones is circular: on the last page of the book only one column
    carries text, and the running head plus the footer are the only blocks
    wide enough to form a second right-edge cluster. Dropping the head leaves
    one column, which reads as a single-column page, which then has no width
    limit — so the head is kept and becomes a reference of its own.
    """
    body = entries
    limit = _span_limit(entries) if _has_gutter(entries) else None
    if limit is not None:
        body = _without_spans(entries) or entries
    columns = _supported_columns(body)
    if not columns:
        clusters = _cluster(sorted({round(b.bbox[2]) for b in body}), gap=20.0)
        columns = [max(clusters, key=len)] if clusters else []
    if not columns:
        return [], None

    bounds: list[tuple[float, float]] = []
    for column in columns:
        members = [b for b in body if round(b.bbox[2]) in column]
        left = min(round(b.bbox[0]) for b in members)
        right = Counter(round(b.bbox[2]) for b in members).most_common(1)[0][0]
        bounds.append((float(left), float(right)))
    bounds.sort()
    return bounds, limit


def _has_gutter(entries: list[Block]) -> bool:
    """Whether the page runs more than one column of text.

    Two right-edge clusters are not enough on their own: a running head and a
    centred footer form a pair of clusters on a page whose text is one column.
    A gutter is a pair of clusters that each hold a real share of the blocks
    and whose columns do not overlap.
    """
    supported = _supported_columns(entries)
    if len(supported) < 2:
        return False
    for left, right in zip(supported, supported[1:], strict=False):
        if max(left) > min(right):
            continue
        return True
    return False


def _supported_columns(entries: list[Block]) -> list[list[int]]:
    """Right-edge clusters big enough to be a column rather than stray lines."""
    if not entries:
        return []
    clusters = _cluster(sorted({round(b.bbox[2]) for b in entries}), gap=20.0)
    min_support = max(2, len(entries) // 20)
    return [
        column
        for column in clusters
        if sum(1 for b in entries if round(b.bbox[2]) in column) >= min_support
    ]


def _without_spans(entries: list[Block]) -> list[Block]:
    """The blocks that fit in a column, dropping full-width page furniture.

    A running head ("Bibliography 465") is as wide as the text block and ends
    at the page's right margin, which is also the right column's right edge.
    It therefore joins the right column's cluster and drags that column's left
    edge back to the page margin, so every real entry in the column looks
    indented and the whole column is absorbed into one entry. The footer is
    narrower and centred, so it lands in no cluster at all and needs no rule
    of its own.
    """
    limit = _span_limit(entries)
    if limit is None:
        return entries
    return [block for block in entries if block.bbox[2] - block.bbox[0] <= limit]


def _span_limit(entries: list[Block]) -> float | None:
    """How wide a block may be before it counts as spanning the page."""
    if not entries:
        return None
    span = max(block.bbox[2] for block in entries) - min(block.bbox[0] for block in entries)
    if span <= 0:
        return None
    return span * _SPAN_RATIO


def _cluster(values: list[int], gap: float) -> list[list[int]]:
    """Group sorted numbers that lie within `gap` of each other."""
    groups: list[list[int]] = []
    for value in values:
        if groups and value - groups[-1][-1] <= gap:
            groups[-1].append(value)
        else:
            groups.append([value])
    return groups
