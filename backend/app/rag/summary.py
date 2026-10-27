"""Two-level index: section summaries over block chunks (T2.5).

01 §9 retrieves chunks, and a chunk is the unit an answer cites. For a 541-page
book that is not enough on its own: a question about "regularization" matches
hundreds of paragraphs, and the reader's real question is usually "which
chapter covers this". So the index has two levels:

  * **section** — one row per heading, holding that section's title and a
    summary of its opening text. Coarse, cheap, and the thing a reader scans;
  * **chunk** — the block-level rows 01 §9 specifies, each pointing at the
    section above it.

The summary is extractive, not generated. A generated summary of a 40-page
chapter is exactly the kind of text H02 forbids: fluent, plausible, and not
traceable to a line of the document. Taking the section's own opening
sentences keeps every word anchored, and it costs no LLM call per section of a
book with 181 headings.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from ..models.schemas import Block

logger = logging.getLogger(__name__)

# How much of a section's opening text the summary keeps. Enough to tell two
# chapters apart in a list, short enough to read at a glance.
SUMMARY_CHARS = 400
# A sentence ends here; the summary is cut on one of these rather than mid-word.
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class SectionSummary:
    """One level of the index: a heading and what follows it."""

    section_id: str
    title: str
    page: int
    summary: str
    block_ids: list[str] = field(default_factory=list)
    # Depth in the heading tree, carried from the outline so a book whose
    # headings are not numbered still gets a nested tree (T2.6).
    level: int = 1


def summarise_sections(
    blocks: list[Block],
    titles: dict[str, str],
    levels: dict[str, int] | None = None,
) -> list[SectionSummary]:
    """Group blocks by section and summarise each from its own text.

    `titles` maps a section id to the heading text the outline gave it; a
    section missing from it (a heading the tree did not place) still gets a
    row, titled by its first block, so no text falls out of the index.
    """
    sections: dict[str, SectionSummary] = {}
    order: list[str] = []
    for block in blocks:
        if block.type == "heading":
            continue
        section_id = block.section_id or "s0"
        if section_id not in sections:
            sections[section_id] = SectionSummary(
                section_id=section_id,
                title=titles.get(section_id, ""),
                page=block.page,
                summary="",
                level=(levels or {}).get(section_id, 1),
            )
            order.append(section_id)
        sections[section_id].block_ids.append(block.id)

    for section_id in order:
        summary = sections[section_id]
        texts = _texts_of(blocks, set(summary.block_ids))
        summary.summary = _opening(texts)
        if not summary.title:
            summary.title = texts[0][:80] if texts else section_id
    return [sections[section_id] for section_id in order]


def _texts_of(blocks: list[Block], wanted: set[str]) -> list[str]:
    return [block.text.strip() for block in blocks if block.id in wanted and block.text.strip()]


def _opening(texts: list[str]) -> str:
    """The section's first sentences, cut on a sentence boundary.

    A section that opens with a table or a formula has no prose to quote; its
    first block is used as-is rather than leaving the summary empty.
    """
    if not texts:
        return ""
    joined = " ".join(texts)
    if len(joined) <= SUMMARY_CHARS:
        return joined
    head = joined[:SUMMARY_CHARS]
    parts = _SENTENCE.split(head)
    if len(parts) > 1:
        head = " ".join(parts[:-1])
    return head.strip() or joined[:SUMMARY_CHARS].strip()
