"""`POST /qa`: the SSE answer stream (01 §5.2, T3.3/T3.4).

Events, in the contract's order: `token` for each verified sentence, `anchor`
when a marker first appears, then `done` with the whole `QAAnswer`, or `error`
with the H17 envelope. The stream sends an SSE comment every ten seconds while
retrieval, reranking and generation run, because a first byte that takes 30
seconds looks like a dead connection to proxies and to the browser. Compare
mode emits the deterministic summary as one `token` and the `CompareTable`
inside `done`; its anchors live on the cells, not on markers.

Retrieval needs the request's DB session, so the pipeline runs as a task inside
the streaming generator rather than as a dependency: the session's lifetime
then covers the stream, and a client disconnect cancels the work instead of
leaving it running.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..deps import SessionDep
from ..errors import AppError, InvalidRequest
from ..llm.errors import LLMError
from ..qa.answer import run_qa
from ..qa.compare import run_compare
from ..rag.retrieve import Scope

logger = logging.getLogger(__name__)

router = APIRouter(tags=["qa"])

KEEPALIVE_S = 10.0


class ScopeBody(BaseModel):
    type: Literal["doc", "set", "all"] = "doc"
    doc_ids: list[str] = Field(default_factory=list)


class AskBody(BaseModel):
    """The openapi `QARequest` shape."""

    question: str = Field(min_length=1, max_length=2000)
    scope: ScopeBody
    mode: Literal["qa", "compare"] = "qa"
    session_id: str | None = None


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _error_payload(code: str, message: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "detail": detail or {}}}


@router.post("/qa")
async def ask(request: Request, body: AskBody, session: SessionDep) -> StreamingResponse:
    question = body.question.strip()
    if not question:
        raise InvalidRequest("问题不能为空")
    scope = Scope(type=body.scope.type, doc_ids=list(body.scope.doc_ids))

    async def events() -> AsyncIterator[str]:
        if body.mode == "compare":
            task = asyncio.create_task(run_compare(session, question, scope))
        else:
            task = asyncio.create_task(run_qa(session, question, scope))
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=KEEPALIVE_S)
                if done:
                    break
                if await request.is_disconnected():
                    return
                yield ": keepalive\n\n"
            try:
                outcome = task.result()
            except AppError as exc:
                yield _sse("error", exc.to_payload())
                return
            except LLMError as exc:
                logger.warning("qa generation failed: %s", exc)
                yield _sse("error", _error_payload("llm_unavailable", "语言模型暂时不可用，请稍后重试"))
                return
            except Exception as exc:  # notified to the client and logged; never swallowed
                logger.exception("qa pipeline failed")
                detail = {"type": type(exc).__name__}
                yield _sse("error", _error_payload("internal_error", "问答处理失败，请稍后重试", detail))
                return
            for name, data in outcome.events:
                yield _sse(name, data)
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
