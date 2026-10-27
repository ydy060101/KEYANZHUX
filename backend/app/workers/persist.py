"""Persisting a parse one window at a time (T2.5).

`persist_parse` replaces a document's rows in a single transaction, which is
right for a 15-page paper and wrong for a 541-page book: nothing is readable
until the last page is done, and an interrupted run leaves nothing behind.

The windowed path writes each window as it finishes. That gives three things
the card asks for:

  * a finished window is retrievable before the next one starts;
  * progress is a fraction of windows, not of an opaque page loop;
  * a killed job resumes from the first window without rows (H12: re-running
    a window replaces its own rows, so running it twice changes nothing).

The last window commits the document-wide parts — the bibliography and the
status — because only then is the whole document known.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.orm import AssetRow, CitationRow, Document, ReferenceRow
from ..models.orm import Block as BlockRow
from ..models.schemas import Asset, Block, Citation, DocumentModel, Reference

logger = logging.getLogger(__name__)


async def window_done(session: AsyncSession, doc_id: str, start: int, end: int) -> bool:
    """Whether this window's rows are already stored.

    A block id carries its page (`b12_3`), so the window's own page range is
    the query — no extra bookkeeping column, and the answer cannot disagree
    with the data it describes.

    A window with no text at all (blank pages, a scan without OCR) stores no
    blocks, so it reads as "not done" and is parsed again on resume. That is
    the cheap direction to be wrong in: re-parsing an empty window costs
    nothing, while treating a real one as done would silently lose its pages.
    """
    count = await session.scalar(
        select(func.count())
        .select_from(BlockRow)
        .where(BlockRow.doc_id == doc_id, BlockRow.page.between(start, end))
    )
    return bool(count)


async def load_window_blocks(session: AsyncSession, doc_id: str, start: int, end: int) -> list[Block]:
    """The stored blocks of one window, in reading order.

    A resumed run needs them to rebuild the section tracker and the chunker's
    open buffer: both are in-memory state that a killed process does not keep,
    and both decide what the *next* window's rows look like.
    """
    rows = await session.scalars(
        select(BlockRow)
        .where(BlockRow.doc_id == doc_id, BlockRow.page.between(start, end))
        .order_by(BlockRow.reading_order)
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
            confidence=row.confidence,
        )
        for row in rows
    ]


async def clear_document(session: AsyncSession, doc_id: str) -> None:
    """Drop a document's parsed rows before a fresh run.

    A resumed run must not keep rows from a run that used a different window
    size: the same pages would be stored twice under ids from two id schemes.
    """
    for table in (BlockRow, ReferenceRow, CitationRow, AssetRow):
        await session.execute(delete(table).where(table.doc_id == doc_id))
    await session.flush()


async def persist_window(
    session: AsyncSession,
    doc_id: str,
    blocks: list[Block],
    assets: list[Asset],
    *,
    first_window: bool = False,
    last_window: bool = False,
    references: list[Reference] | None = None,
    citations: list[Citation] | None = None,
) -> None:
    """Write one window's rows, replacing any left by an earlier attempt.

    Deletion is scoped to the window's pages, so persisting window 5 twice
    cannot disturb windows 1–4 (H12). References and citations are
    document-wide and only arrive on the last window, which replaces them
    wholesale — they have no page range of their own.
    """
    pages = sorted({block.page for block in blocks})
    if pages:
        await session.execute(
            delete(BlockRow).where(BlockRow.doc_id == doc_id, BlockRow.page.in_(pages))
        )
        await session.execute(
            delete(AssetRow).where(AssetRow.doc_id == doc_id, AssetRow.page.in_(pages))
        )
    if references is not None:
        await session.execute(delete(ReferenceRow).where(ReferenceRow.doc_id == doc_id))
    if citations is not None:
        await session.execute(delete(CitationRow).where(CitationRow.doc_id == doc_id))

    session.add_all(
        [
            BlockRow(
                doc_id=doc_id,
                id=block.id,
                type=block.type,
                page=block.page,
                bbox=block.bbox,
                reading_order=block.reading_order,
                section_id=block.section_id,
                text=block.text,
                confidence=block.confidence,
            )
            for block in blocks
        ]
    )
    session.add_all(
        [
            AssetRow(
                id=f"{doc_id}:{asset.id}",
                doc_id=doc_id,
                kind=asset.kind,
                page=asset.page,
                bbox=asset.bbox,
                path=asset.path,
            )
            for asset in assets
        ]
    )
    if references:
        session.add_all([_reference_row(doc_id, item) for item in references])
    if citations:
        session.add_all([_citation_row(doc_id, item) for item in citations])

    doc = await session.get(Document, doc_id)
    if doc is None:
        raise ValueError(f"文档不存在：{doc_id}")
    if first_window:
        doc.status = "parsing"
    if last_window:
        doc.status = "ready"
    await session.flush()
    await session.commit()


def _reference_row(doc_id: str, reference: Reference) -> ReferenceRow:
    return ReferenceRow(
        id=f"{doc_id}:{reference.id}",
        doc_id=doc_id,
        index=reference.index,
        raw=reference.raw,
        title=reference.title,
        authors=reference.authors,
        year=reference.year,
        doi=reference.doi,
        arxiv_id=reference.arxiv_id,
        block_id=reference.block_id,
        bbox=reference.bbox,
    )


def _citation_row(doc_id: str, citation: Citation) -> CitationRow:
    return CitationRow(
        id=f"{doc_id}:{citation.id}",
        doc_id=doc_id,
        marker=citation.marker,
        ref_ids=citation.ref_ids,
        block_id=citation.block_id,
        bbox=citation.bbox,
        method=citation.method,
    )


async def persist_parse(session: AsyncSession, model: DocumentModel) -> None:
    """Replace a document's parsed rows in one transaction (idempotent, H12).

    Kept for the single-pass path (short papers, tests): the windowed path
    above is the same data written a window at a time.
    """
    doc = await session.get(Document, model.doc_id)
    if doc is None:
        raise ValueError(f"文档不存在：{model.doc_id}")

    await session.execute(delete(BlockRow).where(BlockRow.doc_id == model.doc_id))
    await session.execute(delete(ReferenceRow).where(ReferenceRow.doc_id == model.doc_id))
    await session.execute(delete(CitationRow).where(CitationRow.doc_id == model.doc_id))
    await session.execute(delete(AssetRow).where(AssetRow.doc_id == model.doc_id))

    session.add_all(
        [
            BlockRow(
                doc_id=model.doc_id,
                id=block.id,
                type=block.type,
                page=block.page,
                bbox=block.bbox,
                reading_order=block.reading_order,
                section_id=block.section_id,
                text=block.text,
                confidence=block.confidence,
            )
            for block in model.blocks
        ]
    )
    session.add_all([_reference_row(model.doc_id, item) for item in model.references])
    session.add_all([_citation_row(model.doc_id, item) for item in model.citations])
    session.add_all(
        [
            AssetRow(
                id=f"{model.doc_id}:{asset.id}",
                doc_id=model.doc_id,
                kind=asset.kind,
                page=asset.page,
                bbox=asset.bbox,
                path=asset.path,
            )
            for asset in model.assets
        ]
    )
    doc.title = model.meta.title or doc.title
    doc.arxiv_id = model.arxiv_id or doc.arxiv_id
    doc.version = model.version or doc.version
    doc.page_count = model.page_count
    doc.source_kind = model.source_kind
    doc.status = "ready"
    await session.flush()
    # This function owns its transaction: closing the session without a commit
    # would silently discard every row above while the job still reports success.
    await session.commit()


def stats_of(model: DocumentModel) -> dict[str, Any]:
    """Counts the job result reports, from the model it just built."""
    return {
        "blocks": len(model.blocks),
        "references": len(model.references),
        "citations": len(model.citations),
        "assets": len(model.assets),
    }
