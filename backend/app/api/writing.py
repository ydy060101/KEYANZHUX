"""Writing endpoints (01 §5.6, T7.1).

`POST /writing/outline` streams: planning, searching, verifying and writing
each take long enough that a silent connection looks dead, so the route emits a
`stage` event per step and an SSE comment every ten seconds in between. The
draft is committed before the `done` event, so its BibTeX is immediately
downloadable.

`POST /writing/references/verify` answers synchronously because its callers
send at most twenty titles; it never turns "the database was unreachable" into
`verified`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..deps import SessionDep
from ..errors import AppError, InvalidRequest, NotFound
from ..llm.errors import LLMError
from ..models.orm import Draft
from ..writing import outline as outline_service
from ..writing.bibtex import to_bibtex
from ..writing.verify import MAX_TITLES, verify_titles

logger = logging.getLogger(__name__)

router = APIRouter(tags=["writing"])

KEEPALIVE_S = 10.0


class OutlineBody(BaseModel):
    idea: str = Field(min_length=1, max_length=outline_service.MAX_IDEA)
    language: Literal["en", "zh"] = "zh"
    venue: str | None = None


class VerifyBody(BaseModel):
    titles: list[str] = Field(min_length=1, max_length=MAX_TITLES)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _error(code: str, message: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "detail": detail or {}}}


@router.post("/writing/outline")
async def create_outline(request: Request, body: OutlineBody, session: SessionDep) -> StreamingResponse:
    idea = body.idea.strip()
    if not idea:
        raise InvalidRequest("研究想法不能为空")
    payload = outline_service.OutlineInput(idea=idea, language=body.language, venue=body.venue)

    async def events() -> AsyncIterator[str]:
        queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()

        async def emit(name: str, data: dict[str, Any]) -> None:
            await queue.put((name, data))

        async def work() -> None:
            try:
                await outline_service.generate_outline(session, payload, emit)
            except AppError as exc:
                await emit("error", exc.to_payload())
            except LLMError as exc:
                logger.warning("outline generation failed: %s", exc)
                await emit("error", _error("llm_unavailable", "语言模型暂时不可用，请稍后重试"))
            except Exception as exc:  # reported, logged, never swallowed
                logger.exception("outline pipeline failed")
                await emit(
                    "error",
                    _error("internal_error", "框架生成失败，请稍后重试", {"type": type(exc).__name__}),
                )
            finally:
                await queue.put(None)

        task = asyncio.create_task(work())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), KEEPALIVE_S)
                except TimeoutError:
                    if await request.is_disconnected():
                        return
                    yield ": keepalive\n\n"
                    continue
                if item is None:
                    return
                yield _sse(*item)
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


@router.post("/writing/references/verify")
async def verify_references(body: VerifyBody) -> list[dict[str, Any]]:
    seen: set[str] = set()
    titles: list[str] = []
    for raw in body.titles:
        title = " ".join(raw.split()).strip()
        if not title or title.casefold() in seen:
            continue
        seen.add(title.casefold())
        titles.append(title)
    if not titles:
        raise InvalidRequest("请至少提供一个文献标题")
    if len(titles) > MAX_TITLES:
        raise InvalidRequest(f"一次最多校验 {MAX_TITLES} 个标题")
    return await verify_titles(titles)


@router.get("/writing/drafts/{draft_id}/bibtex")
async def draft_bibtex(draft_id: str, session: SessionDep) -> PlainTextResponse:
    draft = await session.get(Draft, draft_id)
    if draft is None:
        raise NotFound("草稿不存在")
    items = (draft.references or {}).get("items") or []
    text = to_bibtex([item for item in items if item.get("status") == "verified"])
    return PlainTextResponse(text, media_type="text/plain; charset=utf-8")
