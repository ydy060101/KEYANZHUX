"""Job queue backed by the `jobs` table plus Redis pub/sub for SSE.

arq runs the workers; the API only creates rows and streams their state. When
Redis is unreachable the job still runs in-process so the demo degrades rather
than failing (H08).
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

from ..db import get_session_factory
from ..errors import NotFound
from ..models.orm import Job

logger = logging.getLogger(__name__)

TERMINAL = {"succeeded", "failed", "cancelled"}


def channel(job_id: str) -> str:
    return f"job:{job_id}"


async def create_job(session: AsyncSession, *, kind: str, payload: dict[str, Any], user: str) -> Job:
    job = Job(kind=kind, payload=payload, created_by=user, status="queued", stage="queued")
    session.add(job)
    await session.flush()
    return job


async def get_job(session: AsyncSession, job_id: str) -> Job:
    job = await session.get(Job, job_id)
    if job is None:
        raise NotFound("任务不存在", detail={"job_id": job_id})
    return job


async def update_job(
    session: AsyncSession,
    job_id: str,
    *,
    status: str | None = None,
    stage: str | None = None,
    progress: float | None = None,
    error: str | None = None,
    result: dict[str, Any] | None = None,
) -> Job:
    job = await get_job(session, job_id)
    if status is not None:
        job.status = status
    if stage is not None:
        job.stage = stage
    if progress is not None:
        job.progress = max(0.0, min(1.0, progress))
    if error is not None:
        job.error = error
    if result is not None:
        job.result = result
    job.updated_at = datetime.now(UTC)
    await session.flush()
    await publish(job_id, _snapshot(job))
    return job


def _snapshot(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "progress": job.progress,
        "stage": job.stage,
        "error": job.error,
    }


async def publish(job_id: str, payload: dict[str, Any]) -> None:
    """Best-effort fan-out; a missing Redis must not break the job."""
    from ..config import get_settings

    url = get_settings().redis_url
    if not url:
        return
    try:
        from redis.asyncio import Redis

        client = Redis.from_url(url, decode_responses=True)
        try:
            await client.publish(channel(job_id), json.dumps(payload))
        finally:
            await client.aclose()
    except Exception:  # pragma: no cover - Redis is optional at runtime
        logger.debug("job publish skipped: redis unavailable")


async def stream_job(job_id: str) -> AsyncIterator[dict[str, Any]]:
    """Yield job snapshots until the job reaches a terminal state.

    Falls back to polling the database when Redis pub/sub is unavailable.
    """
    from ..config import get_settings

    factory = get_session_factory()
    async with factory() as session:
        job = await get_job(session, job_id)
        yield _snapshot(job)
        if job.status in TERMINAL:
            return

    url = get_settings().redis_url
    if url:
        try:
            from redis.asyncio import Redis

            client = Redis.from_url(url, decode_responses=True)
            pubsub = client.pubsub()
            await pubsub.subscribe(channel(job_id))
            try:
                while True:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if message and message.get("type") == "message":
                        data = json.loads(message["data"])
                        yield data
                        if data.get("status") in TERMINAL:
                            return
            finally:
                await pubsub.aclose()
                await client.aclose()
            return
        except Exception:  # pragma: no cover - fall through to polling
            logger.debug("job stream fell back to polling")

    for _ in range(3600):
        await asyncio.sleep(1)
        async with factory() as session:
            current = await session.get(Job, job_id)
            if current is None:
                return
            yield _snapshot(current)
            if current.status in TERMINAL:
                return


async def list_jobs(session: AsyncSession, *, limit: int = 50) -> list[Job]:
    rows = await session.scalars(select(Job).order_by(Job.created_at.desc()).limit(limit))
    return list(rows)
