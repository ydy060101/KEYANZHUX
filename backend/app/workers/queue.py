"""Job lifecycle: the `jobs` table, arq dispatch, progress fan-out and SSE.

The table is the source of truth; Redis pub/sub is only a fast path for SSE.
Every transition is written to the table first, so a client that reconnects
always sees the true state even if it missed messages (H07, H08).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session_factory
from ..errors import Conflict, NotFound
from ..logging_setup import job_id_var
from ..models.orm import Job
from .registry import get_handler

logger = logging.getLogger(__name__)

TERMINAL = {"succeeded", "failed", "cancelled"}
ACTIVE = {"queued", "running"}


def channel(job_id: str) -> str:
    return f"job:{job_id}"


class JobService:
    """All writes to a job go through here so state and events stay in sync."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, *, kind: str, payload: dict[str, Any], user: str) -> Job:
        if get_handler(kind) is None:
            raise Conflict(f"未知任务类型：{kind}", detail={"kind": kind})
        job = Job(kind=kind, payload=payload, created_by=user, status="queued", stage="queued")
        self.session.add(job)
        await self.session.flush()
        return job

    async def get(self, job_id: str) -> Job:
        job = await self.session.get(Job, job_id)
        if job is None:
            raise NotFound("任务不存在", detail={"job_id": job_id})
        return job

    async def start(self, job_id: str) -> Job:
        return await self._transition(job_id, status="running", stage="running", progress=0.0)

    async def progress(self, job_id: str, *, stage: str, progress: float, **extra: Any) -> Job:
        return await self._transition(job_id, stage=stage, progress=progress, result_extra=extra)

    async def succeed(self, job_id: str, result: dict[str, Any] | None = None) -> Job:
        return await self._transition(job_id, status="succeeded", progress=1.0, result=result)

    async def fail(self, job_id: str, error: str) -> Job:
        return await self._transition(job_id, status="failed", error=error)

    async def cancel(self, job_id: str) -> Job:
        job = await self.get(job_id)
        if job.status not in ACTIVE:
            raise Conflict("只有排队中或进行中的任务可以取消", detail={"status": job.status})
        return await self._transition(job_id, status="cancelled", stage="cancelled")

    async def retry(self, job_id: str) -> Job:
        job = await self.get(job_id)
        if job.status not in {"failed", "cancelled"}:
            raise Conflict("只有失败或已取消的任务可以重试", detail={"status": job.status})
        return await self._transition(
            job_id, status="queued", stage="queued", progress=0.0, error="", result={}
        )

    async def _transition(
        self,
        job_id: str,
        *,
        status: str | None = None,
        stage: str | None = None,
        progress: float | None = None,
        error: str | None = None,
        result: dict[str, Any] | None = None,
        result_extra: dict[str, Any] | None = None,
    ) -> Job:
        job = await self.get(job_id)
        if status is not None:
            job.status = status
        if stage is not None:
            job.stage = stage
        if progress is not None:
            job.progress = max(0.0, min(1.0, progress))
        if error is not None:
            job.error = error or None
        if result is not None:
            job.result = result
        elif result_extra:
            job.result = {**(job.result or {}), **result_extra}
        job.updated_at = datetime.now(UTC)
        await self.session.flush()
        snapshot = snapshot_of(job)
        await self.session.commit()
        await publish(job_id, snapshot)
        return job


def snapshot_of(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "progress": job.progress,
        "stage": job.stage,
        "error": job.error,
        "result": job.result,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


async def publish(job_id: str, payload: dict[str, Any]) -> None:
    """Best-effort fan-out; a missing Redis must not break the job (H08)."""
    url = get_settings().redis_url
    if not url:
        return
    try:
        from redis.asyncio import Redis

        client = Redis.from_url(url, decode_responses=True)
        try:
            await client.publish(channel(job_id), json.dumps(payload, ensure_ascii=False))
        finally:
            await client.aclose()
    except Exception:  # pragma: no cover - Redis is optional at runtime
        logger.debug("job publish skipped: redis unavailable")


async def enqueue(job_id: str) -> bool:
    """Hand the job to arq. Returns False when the worker pool is unreachable.

    The caller decides whether to run the job in-process instead; the API must
    keep working with Redis down (H08).
    """
    url = get_settings().redis_url
    if not url:
        return False
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(RedisSettings.from_dsn(url))
        try:
            await pool.enqueue_job("run_job", job_id, _job_id=job_id)
        finally:
            await pool.aclose()
        return True
    except Exception as exc:  # pragma: no cover - exercised only with Redis down
        logger.warning("arq enqueue failed, running in-process: %s", exc)
        return False


async def execute(job_id: str) -> None:
    """Run one job to completion. Shared by the arq worker and the API fallback."""
    factory = get_session_factory()
    job_id_var.set(job_id)
    async with factory() as session:
        service = JobService(session)
        job = await service.get(job_id)
        if job.status == "cancelled":
            return
        kind, payload = job.kind, dict(job.payload or {})
        await service.start(job_id)

    handler = get_handler(kind)
    if handler is None:
        async with factory() as session:
            await JobService(session).fail(job_id, f"没有为任务类型 {kind} 注册处理器")
        return

    try:
        result = await handler(job_id, payload)
    except asyncio.CancelledError:
        async with factory() as session:
            await JobService(session).fail(job_id, "任务被取消")
        raise
    except Exception as exc:
        logger.exception("job failed")
        async with factory() as session:
            await JobService(session).fail(job_id, _readable_error(exc))
        return
    finally:
        job_id_var.set(None)

    async with factory() as session:
        service = JobService(session)
        current = await service.get(job_id)
        # A cancel that arrived while the handler ran wins over the result.
        if current.status == "cancelled":
            return
        await service.succeed(job_id, result)


def _readable_error(exc: Exception) -> str:
    message = getattr(exc, "message", None)
    if isinstance(message, str) and message:
        return message
    return f"{type(exc).__name__}: {exc}"[:500]


async def run_in_background(job_id: str) -> None:
    """Fallback path: no worker process, so run the job in this process."""
    try:
        await execute(job_id)
    except Exception:  # pragma: no cover - execute already records failures
        logger.exception("in-process job crashed")


async def stream(job_id: str) -> AsyncIterator[dict[str, Any]]:
    """Yield snapshots until the job reaches a terminal state.

    Redis pub/sub is the fast path; if it is unavailable (or the message was
    published before the subscription existed) polling the table keeps the
    stream correct at the cost of one query per second.
    """
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, job_id)
        if job is None:
            raise NotFound("任务不存在", detail={"job_id": job_id})
        snapshot = snapshot_of(job)
    yield snapshot
    if snapshot["status"] in TERMINAL:
        return

    async for update in _follow(job_id):
        yield update


async def _follow(job_id: str) -> AsyncIterator[dict[str, Any]]:
    """Merge pub/sub events with a slow poll so neither can stall the stream."""
    factory = get_session_factory()
    last: dict[str, Any] = {}
    pubsub = None
    client = None
    url = get_settings().redis_url
    if url:
        try:
            from redis.asyncio import Redis

            client = Redis.from_url(url, decode_responses=True)
            pubsub = client.pubsub()
            await pubsub.subscribe(channel(job_id))
        except Exception:  # pragma: no cover - falls back to polling
            logger.debug("job stream fell back to polling")
            pubsub = None

    try:
        for _ in range(3600):
            if pubsub is not None:
                try:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                except Exception:  # pragma: no cover - Redis dropped mid-stream
                    message = None
                if message and message.get("type") == "message":
                    data = json.loads(message["data"])
                    if data != last:
                        last = data
                        yield data
                        if data.get("status") in TERMINAL:
                            return
                    continue
            async with factory() as session:
                job = await session.get(Job, job_id)
                if job is None:
                    return
                data = snapshot_of(job)
            if data != last:
                last = data
                yield data
                if data["status"] in TERMINAL:
                    return
            if pubsub is None:
                await asyncio.sleep(1)
    finally:
        if pubsub is not None:
            try:
                await pubsub.aclose()
                if client is not None:
                    await client.aclose()
            except Exception:  # pragma: no cover - shutdown path
                logger.debug("job stream cleanup skipped")


async def list_jobs(session: AsyncSession, *, limit: int = 50) -> list[Job]:
    rows = await session.scalars(select(Job).order_by(Job.created_at.desc()).limit(limit))
    return list(rows)
