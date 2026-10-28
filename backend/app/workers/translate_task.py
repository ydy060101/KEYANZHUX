"""The whole-document translation job (T4.2).

Separate from the request path because a paper is minutes of model time
(H07). The handler translates in small batches, reports progress per batch,
and finishes by rendering the Markdown/HTML the card asks for; a re-run reuses
every block whose source text has not changed.
"""

from __future__ import annotations

import logging
from typing import Any

from ..db import get_session_factory
from ..models.orm import Document
from ..translate.service import render_document, translate_document
from .queue import JobService
from .registry import register_handler

logger = logging.getLogger(__name__)


async def translate_job(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    doc_id = str(payload["doc_id"])
    direction = str(payload.get("direction") or "en2zh")
    fmt = str(payload.get("format") or "md")
    factory = get_session_factory()

    from ..llm.gateway import get_gateway

    async with factory() as session:
        doc = await session.get(Document, doc_id)
        if doc is None:
            raise ValueError(f"文档不存在：{doc_id}")
        await JobService(session).progress(job_id, stage="translating", progress=0.01)

        async def report(done: int, total: int) -> None:
            share = done / max(1, total)
            async with factory() as progress_session:
                await JobService(progress_session).progress(
                    job_id, stage=f"translate {done}/{total}", progress=0.01 + 0.94 * share
                )

        result = await translate_document(session, doc_id, direction, get_gateway(), on_progress=report)
        rendered = await render_document(session, doc_id, direction, fmt)

    logger.info(
        "translate job done doc_id=%s translated=%d cached=%d",
        doc_id,
        result["translated"],
        result["cached"],
    )
    return {
        **result,
        "format": fmt,
        "path": rendered["path"],
        "content": rendered["content"][:2000],
    }


register_handler("translate", translate_job)
