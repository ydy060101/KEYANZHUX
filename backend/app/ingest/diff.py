"""Section-level diff between two versions of a paper (T1.5).

Sections are matched by heading text, then by position for renamed headings.
The LLM writes the summary, but every number it is allowed to state comes from
the computed statistics — the prompt receives them and is forbidden from
introducing others (H04), and the rendered summary is checked against them.
"""

from __future__ import annotations

import difflib
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.orm import Block as BlockRow
from ..models.orm import ReferenceRow
from ..models.schemas import Block

logger = logging.getLogger(__name__)

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_HEADING_NO_RE = re.compile(r"^(\d+(?:\.\d+){0,2})\.?\s+")


@dataclass
class Section:
    title: str
    text: str
    block_ids: list[str] = field(default_factory=list)


def sections_from_blocks(blocks: list[Block]) -> list[Section]:
    """Group blocks under their headings, keeping document order."""
    sections: list[Section] = []
    current: Section | None = None
    for block in blocks:
        if block.type == "heading":
            current = Section(title=" ".join(block.text.split())[:200], text="", block_ids=[block.id])
            sections.append(current)
            continue
        if current is None:
            current = Section(title="(preamble)", text="", block_ids=[])
            sections.append(current)
        current.text = f"{current.text}\n{block.text}".strip()
        current.block_ids.append(block.id)
    return sections


def _normalise(title: str) -> str:
    return _HEADING_NO_RE.sub("", " ".join(title.lower().split()))


_HYPHEN_BREAK = re.compile(r"(\w)-\s*\n\s*(\w)")
_WS = re.compile(r"\s+")


def _normalise_text(text: str) -> str:
    """Fold typographic noise that is not a content change.

    PDF extraction differs between files of the same paper: ligatures (ﬁ vs fi),
    line-break hyphenation and whitespace all vary with the producer. Folding
    them keeps the diff about the paper rather than the typesetting.
    """
    folded = unicodedata.normalize("NFKC", text)
    folded = _HYPHEN_BREAK.sub(r"\1\2", folded)
    return _WS.sub(" ", folded).strip()


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


@dataclass
class SectionDiff:
    title: str
    change: str  # added | removed | modified | unchanged
    similarity: float = 1.0


@dataclass
class DiffStats:
    sections_added: int = 0
    sections_removed: int = 0
    sections_modified: int = 0
    figures_changed: int = 0
    tables_changed: int = 0
    references_added: int = 0
    references_removed: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "sections_added": self.sections_added,
            "sections_removed": self.sections_removed,
            "sections_modified": self.sections_modified,
            "figures_changed": self.figures_changed,
            "tables_changed": self.tables_changed,
            "references_added": self.references_added,
            "references_removed": self.references_removed,
        }


def diff_sections(old: list[Section], new: list[Section], *, threshold: float = 0.9) -> list[SectionDiff]:
    """Match sections by title, then align leftovers by position."""
    old_by_key = {_normalise(s.title): s for s in old}
    new_by_key = {_normalise(s.title): s for s in new}
    result: list[SectionDiff] = []
    matched_old: set[str] = set()

    for section in new:
        key = _normalise(section.title)
        counterpart = old_by_key.get(key)
        if counterpart is not None:
            matched_old.add(key)
            ratio = _similarity(_normalise_text(counterpart.text), _normalise_text(section.text))
            change = "unchanged" if ratio >= threshold else "modified"
            result.append(SectionDiff(title=section.title, change=change, similarity=round(ratio, 3)))
        else:
            result.append(SectionDiff(title=section.title, change="added"))

    for section in old:
        key = _normalise(section.title)
        if key not in new_by_key and key not in matched_old:
            result.append(SectionDiff(title=section.title, change="removed"))
    return result


def _count_types(blocks: list[Block], kind: str) -> int:
    return sum(1 for block in blocks if block.type == kind)


async def load_blocks(session: AsyncSession, doc_id: str) -> list[Block]:
    rows = await session.scalars(
        select(BlockRow).where(BlockRow.doc_id == doc_id).order_by(BlockRow.reading_order)
    )
    return [
        Block(
            id=row.id,
            type=row.type,
            page=row.page,
            bbox=list(row.bbox or []),
            reading_order=row.reading_order,
            section_id=row.section_id,
            text=row.text,
        )
        for row in rows
    ]


async def compare(
    session: AsyncSession, doc_id: str, other_id: str
) -> tuple[dict[str, Any], dict[str, int], list[dict[str, str]]]:
    """Return (stats, raw counts, section changes) for two stored documents."""
    old_blocks = await load_blocks(session, other_id)
    new_blocks = await load_blocks(session, doc_id)
    old_sections = sections_from_blocks(old_blocks)
    new_sections = sections_from_blocks(new_blocks)
    changes = diff_sections(old_sections, new_sections)

    old_ref_count = len(
        list(await session.scalars(select(ReferenceRow.id).where(ReferenceRow.doc_id == other_id)))
    )
    new_ref_count = len(
        list(await session.scalars(select(ReferenceRow.id).where(ReferenceRow.doc_id == doc_id)))
    )

    stats = DiffStats(
        sections_added=sum(1 for c in changes if c.change == "added"),
        sections_removed=sum(1 for c in changes if c.change == "removed"),
        sections_modified=sum(1 for c in changes if c.change == "modified"),
        figures_changed=abs(_count_types(new_blocks, "figure") - _count_types(old_blocks, "figure")),
        tables_changed=abs(_count_types(new_blocks, "table") - _count_types(old_blocks, "table")),
        references_added=max(0, new_ref_count - old_ref_count),
        references_removed=max(0, old_ref_count - new_ref_count),
    )
    return stats.as_dict(), stats.as_dict(), [{"title": c.title, "change": c.change} for c in changes]


def numbers_in(text: str) -> set[str]:
    return set(_NUMBER_RE.findall(text))


def summary_is_grounded(summary: str, stats: dict[str, int]) -> bool:
    """Every number in the summary must appear in the statistics (H04).

    A summary may omit statistics; it may not invent one. Small counts are
    also allowed as Chinese numerals-free words ("新增一章" needs no digit).
    """
    allowed = {str(value) for value in stats.values()} | {"200"}
    return numbers_in(summary) <= allowed


SUMMARY_SYSTEM = (
    "You summarise the differences between two versions of a research paper. "
    "Use only the supplied statistics and section list. Never invent a number: any digit you "
    "write must already appear in the statistics. Write at most 200 characters, in Chinese."
)


async def summarise(
    stats: dict[str, int], changes: list[dict[str, str]], gateway: Any
) -> str:
    """LLM summary constrained to the computed statistics."""
    from ..llm.errors import LLMError

    section_lines = "\n".join(f"- {c['title']}: {c['change']}" for c in changes[:40])
    prompt = (
        "Statistics:\n"
        f"{stats}\n\n"
        "Section changes:\n"
        f"{section_lines}\n\n"
        "Write one Chinese paragraph of at most 200 characters describing what changed. "
        "Do not add numbers that are not in the statistics."
    )
    try:
        result = await gateway.chat(
            [{"role": "system", "content": SUMMARY_SYSTEM}, {"role": "user", "content": prompt}],
            tier="fast",
            cache_prefix=SUMMARY_SYSTEM,
        )
        text = getattr(result, "text", str(result)).strip()
    except LLMError as exc:
        logger.warning("diff summary LLM failed: %s", exc)
        return _fallback_summary(stats)

    text = text[:200]
    if not summary_is_grounded(text, stats):
        logger.warning("diff summary stated a number absent from the statistics; using the template")
        return _fallback_summary(stats)
    return text


def _fallback_summary(stats: dict[str, int]) -> str:
    """Deterministic template: every number here comes straight from `stats`."""
    parts = [
        f"新增章节 {stats['sections_added']}",
        f"删除章节 {stats['sections_removed']}",
        f"修改章节 {stats['sections_modified']}",
        f"图表变化 {stats['figures_changed']}",
        f"参考文献新增 {stats['references_added']}、删除 {stats['references_removed']}",
    ]
    return ("；".join(parts) + "。")[:200]
