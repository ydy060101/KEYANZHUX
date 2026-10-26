"""Job endpoints: status, SSE progress, cancel and retry (01 §5.1, T1.1)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..deps import SessionDep
from ..workers import queue
from ..workers.queue import JobService, snapshot_of

router = APIRouter(tags=["jobs"])


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# Declared before `/jobs/{job_id}` so the literal path wins the match.
@router.get("/jobs/stream")
async def stream_job(request: Request, job_id: str) -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        async for snapshot in queue.stream(job_id):
            if await request.is_disconnected():
                return
            status = snapshot["status"]
            if status in queue.TERMINAL:
                yield _sse("done", snapshot)
                return
            yield _sse("progress", snapshot)
        # The generator ended without a terminal event (e.g. the job vanished).
        yield _sse("error", {"error": {"code": "stream_closed", "message": "任务流已关闭"}})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, session: SessionDep) -> dict[str, Any]:
    job = await JobService(session).get(job_id)
    return snapshot_of(job)


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, session: SessionDep) -> dict[str, Any]:
    job = await JobService(session).cancel(job_id)
    return snapshot_of(job)


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: str, session: SessionDep) -> dict[str, Any]:
    job = await JobService(session).retry(job_id)
    snapshot = snapshot_of(job)
    if not await queue.enqueue(job_id):
        # No worker process: run it here so the retry still happens (H08).
        import asyncio

        asyncio.create_task(queue.run_in_background(job_id))
    return snapshot
