"""Fill `chunks.embedding` with bge-m3 vectors (T3.1).

The parse job deliberately leaves `embedding` null (`index.py` explains why: a
window must be persisted and searchable without waiting for a 2 GB model to
load). This module is the pass that fills them in, and it is a job of its own
(`kind="embed"`) for the same reason: it is slow, it is resumable, and the
document is already readable and BM25-searchable while it runs (H07, H08).

Three properties matter more than throughput:

  * **Resumable (H12)** — it selects chunks whose `embedding IS NULL`, so a
    killed job picks up where it stopped, and running it twice embeds nothing
    the second time.
  * **Bounded (H11)** — it reads and writes one page of chunks at a time, so
    peak memory is the model plus one batch, not the whole book.
  * **Degradable (H08)** — when the model cannot load, the job *fails with a
    readable message* rather than silently succeeding with no vectors; the
    chunks stay null and BM25 keeps working, and the user can retry.

Text sent to the model is the chunk's own text. No title, no heading, no
prefix: an embedding that mixes in text from elsewhere would match a query
about the title for reasons the anchor cannot show (H01).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.orm import Chunk
from .embedding import Embedder

logger = logging.getLogger(__name__)

ProgressHook = Callable[[int, int], Awaitable[None]]

# Chunks per database round trip. Small enough that a 3 000-chunk book never
# holds more than a few megabytes of text plus vectors at once, large enough
# that the model sees a real batch.
BATCH = 64


@dataclass
class EmbedResult:
    """What the pass did, for the job result and the logs."""

    doc_id: str
    embedded: int
    remaining: int
    skipped: int
    model: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "embedded": self.embedded,
            "remaining": self.remaining,
            "skipped": self.skipped,
            "model": self.model,
        }


async def pending_count(session: AsyncSession, doc_id: str) -> int:
    """How many of this document's chunks still need a vector."""
    value = await session.scalar(
        select(func.count()).select_from(Chunk).where(
            Chunk.doc_id == doc_id, Chunk.embedding.is_(None)
        )
    )
    return int(value or 0)


async def embed_document(
    session: AsyncSession,
    doc_id: str,
    embedder: Embedder,
    *,
    on_progress: ProgressHook | None = None,
) -> EmbedResult:
    """Embed every chunk of `doc_id` that has no vector yet.

    `on_progress(done, total)` is called after each batch; the job handler
    turns it into a progress event. It is awaited, so a slow SSE consumer
    slows the pass rather than piling up tasks.
    """
    total = await pending_count(session, doc_id)
    if total == 0:
        return EmbedResult(doc_id=doc_id, embedded=0, remaining=0, skipped=0, model=_name(embedder))

    if not await _available(embedder):
        raise EmbedUnavailable(
            "嵌入模型不可用，向量索引未生成；全文检索仍可用，可稍后重试",
            detail={"model": _name(embedder), "error": embedder.load_error},
        )

    done = 0
    skipped = 0
    # Offset stays at 0 while rows are being filled: each batch removes itself
    # from the "embedding IS NULL" set, so the next page starts where this one
    # stopped. A cursor on `id` would need the ids to be ordered consistently
    # with the null filter, which they are not after a partial run.
    while True:
        rows = await _next_batch(session, doc_id)
        if not rows:
            break
        texts = [row.text for row in rows]
        vectors = await embedder.embed(texts)
        if vectors is None or len(vectors) != len(rows):
            raise EmbedUnavailable(
                "嵌入模型未返回向量，向量索引未生成；全文检索仍可用，可稍后重试",
                detail={"model": _name(embedder), "batch": len(rows)},
            )
        for row, vector in zip(rows, vectors, strict=True):
            await session.execute(
                update(Chunk).where(Chunk.id == row.id).values(embedding=[float(x) for x in vector])
            )
            done += 1
        # Commit per batch: a killed job keeps the vectors it finished (H12).
        await session.commit()
        if on_progress is not None:
            await on_progress(done, total)
        if done >= total:
            break

    remaining = await pending_count(session, doc_id)
    logger.info("embedded doc_id=%s count=%d remaining=%d skipped=%d", doc_id, done, remaining, skipped)
    return EmbedResult(
        doc_id=doc_id, embedded=done, remaining=remaining, skipped=skipped, model=_name(embedder)
    )


class EmbedUnavailable(Exception):
    """The model could not produce vectors; the job reports this (H08)."""

    def __init__(self, message: str, *, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


async def _available(embedder: Embedder) -> bool:
    """Load the model once, so an unavailable one fails before any work.

    `embed()` would discover the same thing on the first batch, but by then the
    job has already reported progress and the user has been told it is running.
    """
    probe = await embedder.embed(["probe"], load=True)
    return probe is not None


async def _next_batch(session: AsyncSession, doc_id: str) -> list[Chunk]:
    """One page of chunks still missing a vector, in reading order."""
    result = await session.scalars(
        select(Chunk)
        .where(Chunk.doc_id == doc_id, Chunk.embedding.is_(None))
        .order_by(Chunk.page_start, Chunk.id)
        .limit(BATCH)
    )
    return list(result)


def _name(embedder: Embedder) -> str:
    return getattr(embedder, "_model_name", "unknown")
