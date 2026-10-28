"""Translation endpoints (01 §5.3, T4.1/T4.2, T7.4).

`POST /translate/selection` streams: the reader's toolbar shows the first
characters while the rest is still being generated. `POST
/documents/{id}/translate` returns a `job_id` because a whole paper is minutes
of work (H07), and `GET /documents/{id}/translation` serves the aligned rows
the bilingual view and the Markdown/HTML export need. `POST /translate/zh2en`
is the contract's synchronous academic-English endpoint for abstracts and
short papers; long text belongs in the document job.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from ..deps import SessionDep, UserIdDep
from ..errors import AppError, Conflict, InvalidRequest, NotFound
from ..llm.errors import LLMError
from ..models.orm import Block as BlockRow
from ..models.orm import Document, Translation
from ..translate.academic import MAX_INPUT_CHARS, translate_academic
from ..translate.glossary import (
    MAX_ENTRIES,
    MAX_SOURCE,
    MAX_TARGET,
    load_glossary,
    save_glossary,
)
from ..translate.render import render_document
from ..translate.service import (
    LANG,
    stream_translation,
)
from ..workers import queue

logger = logging.getLogger(__name__)

router = APIRouter(tags=["translate"])

KEEPALIVE_S = 10.0
Direction = Literal["en2zh", "zh2en"]


class SelectionBody(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    block_id: str | None = None
    direction: Direction = "en2zh"


class DocumentBody(BaseModel):
    format: Literal["md", "html"] = "md"
    direction: Direction | None = None


class AcademicBody(BaseModel):
    text: str = Field(max_length=MAX_INPUT_CHARS)
    block_id: str | None = None
    direction: Direction = "zh2en"


class GlossaryEntryBody(BaseModel):
    source: str = Field(min_length=1, max_length=MAX_SOURCE)
    target: str = Field(min_length=1, max_length=MAX_TARGET)

    @field_validator("source", "target")
    @classmethod
    def _one_line(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("术语不能为空")
        if "\n" in value or "\r" in value:
            raise ValueError("术语不能包含换行")
        return value


class GlossaryBody(BaseModel):
    entries: list[GlossaryEntryBody] = Field(default_factory=list, max_length=MAX_ENTRIES)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _error(code: str, message: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "detail": detail or {}}}


async def _detect_direction(session: Any, doc_id: str) -> Direction:
    """Chinese source → translate to English; anything else → Chinese."""
    sample = (
        (
            await session.execute(
                select(BlockRow.text)
                .where(BlockRow.doc_id == doc_id, BlockRow.type == "paragraph")
                .order_by(BlockRow.page, BlockRow.reading_order)
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    text = "".join(sample)[:4000]
    if not text:
        return "en2zh"
    cjk = sum(1 for char in text if "一" <= char <= "鿿")
    return "zh2en" if cjk / len(text) > 0.3 else "en2zh"


@router.get("/translate/glossary")
async def get_glossary(user: UserIdDep) -> dict[str, Any]:
    """The reader's terminology list and the version its cache keys use."""
    return load_glossary(user).as_payload()


@router.put("/translate/glossary")
async def put_glossary(body: GlossaryBody, user: UserIdDep) -> dict[str, Any]:
    """Replace the list (add and delete are both edits of the whole list)."""
    try:
        glossary = save_glossary(user, [entry.model_dump() for entry in body.entries])
    except ValueError as exc:
        raise InvalidRequest(str(exc)) from exc
    return glossary.as_payload()


@router.post("/translate/selection")
async def translate_selection(
    request: Request, body: SelectionBody, session: SessionDep, user: UserIdDep
) -> StreamingResponse:
    text = body.text.strip()
    if not text:
        raise InvalidRequest("没有可翻译的文本")
    if body.block_id is not None:
        exists = await session.scalar(select(BlockRow.id).where(BlockRow.id == body.block_id).limit(1))
        if exists is None:
            raise NotFound("原文块不存在", detail={"block_id": body.block_id})

    from ..llm.gateway import get_gateway

    glossary = load_glossary(user)

    async def events() -> AsyncIterator[str]:
        items: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()

        async def pump() -> None:
            try:
                async for name, data in stream_translation(text, body.direction, get_gateway(), glossary=glossary):
                    await items.put((name, data))
            except AppError as exc:
                await items.put(("error", exc.to_payload()))
            except LLMError as exc:
                logger.warning("selection translation failed: %s", exc)
                await items.put(("error", _error("llm_unavailable", "翻译服务暂时不可用，请稍后重试")))
            except Exception as exc:  # reported to the client, never swallowed
                logger.exception("selection translation crashed")
                await items.put(("error", _error("internal_error", "翻译失败", {"type": type(exc).__name__})))
            finally:
                await items.put(None)

        task = asyncio.create_task(pump())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(items.get(), KEEPALIVE_S)
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


@router.post("/translate/zh2en")
async def translate_zh2en(body: AcademicBody, session: SessionDep, user: UserIdDep) -> dict[str, Any]:
    """Chinese abstract or short paper → academic English (synchronous)."""
    text = body.text.strip()
    if not text:
        raise InvalidRequest("没有可翻译的文本")
    if body.direction != "zh2en":
        raise InvalidRequest("该接口只支持中文到英文", detail={"direction": body.direction})
    if body.block_id is not None:
        exists = await session.scalar(select(BlockRow.id).where(BlockRow.id == body.block_id).limit(1))
        if exists is None:
            raise NotFound("原文块不存在", detail={"block_id": body.block_id})

    from ..llm.gateway import get_gateway

    try:
        result = await translate_academic(text, get_gateway(), glossary=load_glossary(user))
    except ValueError as exc:
        raise InvalidRequest(str(exc)) from exc
    except LLMError as exc:
        logger.warning("academic translation failed: %s", exc)
        raise AppError(
            "翻译服务暂时不可用，请稍后重试",
            code="llm_unavailable",
            status_code=502,
        ) from exc
    return {"text": result.text, "direction": "zh2en", "cached": result.cached}


@router.post("/documents/{doc_id}/translate")
async def start_document_translation(
    doc_id: str, body: DocumentBody, session: SessionDep, user: UserIdDep
) -> dict[str, Any]:
    doc = await session.get(Document, doc_id)
    if doc is None:
        raise NotFound("文档不存在", detail={"doc_id": doc_id})
    if doc.status not in {"ready", "parsing"}:
        raise Conflict("文献尚未解析完成，暂时无法翻译", detail={"status": doc.status})
    direction = body.direction or await _detect_direction(session, doc_id)
    job = await queue.JobService(session).create(
        kind="translate",
        payload={"doc_id": doc_id, "direction": direction, "format": body.format},
        user=user,
    )
    await session.commit()
    if not await queue.enqueue(job.id):
        asyncio.create_task(queue.run_in_background(job.id))
    return {"doc_id": doc_id, "job_id": job.id, "direction": direction}


@router.get("/documents/{doc_id}/translation")
async def get_translation(
    doc_id: str,
    session: SessionDep,
    direction: Direction = "en2zh",
    format: Literal["md", "html"] | None = Query(default=None),
) -> dict[str, Any]:
    doc = await session.get(Document, doc_id)
    if doc is None:
        raise NotFound("文档不存在", detail={"doc_id": doc_id})
    lang = LANG[direction]
    if format is not None:
        return await render_document(session, doc_id, direction, format)

    rows = (
        await session.execute(
            select(BlockRow, Translation)
            .join(
                Translation,
                (Translation.doc_id == BlockRow.doc_id) & (Translation.block_id == BlockRow.id),
            )
            .where(BlockRow.doc_id == doc_id, Translation.lang == lang)
            .order_by(BlockRow.page, BlockRow.reading_order)
        )
    ).all()
    return {
        "doc_id": doc_id,
        "direction": direction,
        "lang": lang,
        "blocks": [
            {
                "block_id": block.id,
                "page": block.page,
                "type": block.type,
                "bbox": list(block.bbox),
                "original": block.text,
                "translation": translation.text,
            }
            for block, translation in rows
        ],
    }
