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

from ..models.schemas import Block, Reference

logger = logging.getLogger(__name__)

# A heading that is only the word "References" (any capitalisation).
_HEADING = re.compile(r"^(?:\d+\.?\s*)?(references|bibliography|works cited)$", re.IGNORECASE)
# A reference list ends at the first appendix-like heading.
_STOP = re.compile(
    r"^(appendix|attention visualizations|supplementary|acknowledg)", re.IGNORECASE
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

    The list may run over two columns, and each column has its own margin, so
    the margin is computed per column. Comparing against one global minimum
    would make every right-column block look like a continuation.
    """
    margins = _column_margins(entries)
    references: list[Reference] = []
    for block in entries:
        starts_entry = block.bbox[0] <= _margin_for(block, entries, margins) + _MARGIN_TOLERANCE
        if not references or starts_entry:
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


def _column_margins(entries: list[Block]) -> dict[int, float]:
    """Left edge of each page column, keyed by the column's right edge.

    A block's column is identified by its right edge: both columns of a page
    end at a constant right margin, so rounding it separates them without
    knowing the page width. A cluster with almost no members is not a column —
    a single short line ending early would otherwise pass for one and make its
    own text look like an entry start.
    """
    right_edges = sorted({round(block.bbox[2]) for block in entries})
    clusters = _cluster(right_edges, gap=20.0)
    min_support = max(2, len(entries) // 20)
    columns = [
        column
        for column in clusters
        if sum(1 for block in entries if round(block.bbox[2]) in column) >= min_support
    ]
    if not columns:
        columns = [max(clusters, key=len)]

    margins: dict[int, float] = {}
    for column in columns:
        members = [b for b in entries if round(b.bbox[2]) in column]
        margins[column[0]] = min(b.bbox[0] for b in members)
    return margins


def _margin_for(block: Block, entries: list[Block], margins: dict[int, float]) -> float:
    column = min(margins, key=lambda edge: abs(edge - round(block.bbox[2])))
    return margins[column]


def _cluster(values: list[int], gap: float) -> list[list[int]]:
    """Group sorted numbers that lie within `gap` of each other."""
    groups: list[list[int]] = []
    for value in values:
        if groups and value - groups[-1][-1] <= gap:
            groups[-1].append(value)
        else:
            groups.append([value])
    return groups
