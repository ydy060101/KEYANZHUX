"""Writing the retrieval index as windows finish (T2.5).

The index is written per window, not at the end, because the card's
acceptance is "已完成窗口可提前检索": a page must be findable as soon as its
window is parsed. Two levels are written together (see `summary`):

  * a `chunks` row per block group, with `block_ids[]` so a hit maps back to
    anchors (H01, 01 §9);
  * a `section_summaries` row per section, so the reader can search headings
    and titles before the whole book is indexed.

Chunk ids are derived from the chunk's first block (`{doc}:{block_id}`). Block
ids already carry their page (`b12_3`), so the id is stable across runs: a
window that is parsed twice produces the same ids, and writing it twice
replaces its rows instead of duplicating them (H12). A running counter would
have made the second run's ids depend on how far the first one got.

Embeddings are left null here and filled by the embedding pass (T3.1): the
parse worker must not wait on a several-hundred-megabyte model to persist a
window, and full-text search over `text` already makes the window retrievable
in the meantime.
"""

from __future__ import annotations

import logging

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.orm import Chunk, SectionSummaryRow
from ..models.schemas import Block, OutlineItem
from ..rag.chunk import ChunkDraft
from ..rag.summary import SectionSummary, summarise_sections

logger = logging.getLogger(__name__)


def chunk_id(doc_id: str, draft: ChunkDraft) -> str:
    """A chunk's id: its document and the block it starts at."""
    first = draft.block_ids[0] if draft.block_ids else "k0"
    return f"{doc_id}:{first}"


def section_titles(outline: list[OutlineItem]) -> dict[str, str]:
    """Section id → heading text, from the accumulated outline."""
    return {item.id: item.title for item in outline}


async def write_index(
    session: AsyncSession,
    doc_id: str,
    blocks: list[Block],
    outline: list[OutlineItem],
    drafts: list[ChunkDraft],
) -> int:
    """Persist this window's chunks and the sections its blocks belong to.

    Deletion is by chunk id, not by page range: a chunk may span a window
    boundary, and deleting by page would either miss it or take a neighbour
    with it. Deleting exactly the ids being written makes the write
    idempotent whatever the window size (H12).

    Returns how many chunks were written.
    """
    ids = [chunk_id(doc_id, draft) for draft in drafts]
    if ids:
        await session.execute(delete(Chunk).where(Chunk.doc_id == doc_id, Chunk.id.in_(ids)))
        session.add_all(
            [
                Chunk(
                    id=identifier,
                    doc_id=doc_id,
                    block_ids=draft.block_ids,
                    section_id=draft.section_id,
                    page_start=draft.page_start,
                    page_end=draft.page_end,
                    text=draft.text,
                )
                for identifier, draft in zip(ids, drafts, strict=True)
            ]
        )
    await _write_sections(session, doc_id, blocks, outline)
    await session.flush()
    return len(ids)


async def _write_sections(
    session: AsyncSession,
    doc_id: str,
    blocks: list[Block],
    outline: list[OutlineItem],
) -> None:
    """Replace the summary rows for the sections this window's blocks belong to.

    Only those sections: a section that started in window 3 and ends in
    window 4 is rewritten when window 4 closes it, and the sections of earlier
    windows keep the rows they already have.
    """
    sections = summarise_sections(blocks, section_titles(outline))
    if not sections:
        return
    ids = [section.section_id for section in sections]
    await session.execute(
        delete(SectionSummaryRow).where(
            SectionSummaryRow.doc_id == doc_id, SectionSummaryRow.section_id.in_(ids)
        )
    )
    session.add_all([_section_row(doc_id, section) for section in sections])


def _section_row(doc_id: str, section: SectionSummary) -> SectionSummaryRow:
    return SectionSummaryRow(
        doc_id=doc_id,
        section_id=section.section_id,
        title=section.title,
        page=section.page,
        summary=section.summary,
        block_ids=section.block_ids,
    )
