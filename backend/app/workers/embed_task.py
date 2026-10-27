"""The embed job: fill in the vectors T3.1's index needs (T3.1).

Why this is its own job rather than a step of the parse:

  * the parse job's acceptance is "a finished window is searchable"; waiting
    for a 2 GB model to load before a window can be persisted would break that
    (T2.5), so `index.py` writes chunks with `embedding` null;
  * the model is slow on CPU — roughly a minute per hundred chunks on the
    machine this was built on — which is well past the 2 s H07 budget for a
    request, and a parse of the 541-page book already takes long enough;
  * it is resumable and repeatable on its own: a user who loaded a document
    while the model was unavailable runs this once the model is there.

The handler reports progress per batch, so the library's job indicator moves
while it runs.
"""

from __future__ import annotations

import logging
from typing import Any

from ..db import get_session_factory
from ..models.orm import Document
from ..rag.embed_pass import embed_document
from ..rag.embedding import get_embedder
from .queue import JobService
from .registry import register_handler

logger = logging.getLogger(__name__)


async def embed_chunks(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    doc_id = str(payload["doc_id"])
    factory = get_session_factory()

    async with factory() as session:
        doc = await session.get(Document, doc_id)
        if doc is None:
            raise ValueError(f"文档不存在：{doc_id}")
        service = JobService(session)
        await service.progress(job_id, stage="loading", progress=0.02)

        async def report(done: int, total: int) -> None:
            # Loading the model is the first half of the wait on a cold start,
            # so the bar does not reach 1 until the last batch is written.
            share = done / max(1, total)
            async with factory() as progress_session:
                await JobService(progress_session).progress(
                    job_id, stage=f"embed {done}/{total}", progress=0.02 + 0.96 * share
                )

        result = await embed_document(session, doc_id, get_embedder(), on_progress=report)

    logger.info(
        "embed job done doc_id=%s embedded=%d remaining=%d",
        doc_id,
        result.embedded,
        result.remaining,
    )
    return result.as_dict()


register_handler("embed", embed_chunks)
