"""T1.1 acceptance: submit → progress → finish, cancel, retry, SSE framing."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from app.main import create_app
from app.workers import queue
from app.workers.registry import register_handler
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client(session: Any) -> Any:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _make_job(session: Any) -> str:
    service = queue.JobService(session)
    job = await service.create(kind="demo", payload={"n": 1}, user="tester")
    await session.commit()
    return job.id


@pytest.fixture(autouse=True)
def demo_handler() -> Any:
    """A handler that reports progress and finishes, standing in for parse."""

    async def handler(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        from app.db import get_session_factory

        for step in (0.25, 0.5, 0.75):
            await asyncio.sleep(0)
            async with get_session_factory()() as s:
                await queue.JobService(s).progress(job_id, stage="work", progress=step)
        return {"done": True}

    register_handler("demo", handler)
    yield


async def test_submit_progress_finish(session: Any) -> None:
    job_id = await _make_job(session)
    await queue.execute(job_id)

    fresh = await queue.JobService(session).get(job_id)
    await session.refresh(fresh)
    assert fresh.status == "succeeded"
    assert fresh.progress == 1.0
    assert fresh.result == {"done": True}


async def test_cancel_active_job(session: Any) -> None:
    job_id = await _make_job(session)
    cancelled = await queue.JobService(session).cancel(job_id)
    assert cancelled.status == "cancelled"


async def test_cancel_finished_job_conflicts(session: Any) -> None:
    from app.errors import Conflict

    job_id = await _make_job(session)
    await queue.execute(job_id)
    with pytest.raises(Conflict):
        await queue.JobService(session).cancel(job_id)


async def test_retry_requeues_failed_job(session: Any) -> None:
    job_id = await _make_job(session)
    service = queue.JobService(session)
    await service.fail(job_id, "boom")
    retried = await service.retry(job_id)
    assert retried.status == "queued"
    assert retried.error is None


async def test_stream_reaches_terminal_state(session: Any) -> None:
    job_id = await _make_job(session)
    await queue.execute(job_id)

    seen: list[str] = []
    async for snapshot in queue.stream(job_id):
        seen.append(snapshot["status"])
    assert seen[-1] == "succeeded"
    assert "succeeded" in seen


async def test_api_get_job(client: Any, session: Any) -> None:
    job_id = await _make_job(session)
    response = await client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == job_id
    assert body["status"] == "queued"


async def test_api_get_missing_job_uses_error_envelope(client: Any, session: Any) -> None:
    response = await client.get("/api/v1/jobs/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_api_stream_emits_sse_frames(client: Any, session: Any) -> None:
    job_id = await _make_job(session)
    await queue.execute(job_id)
    response = await client.get(f"/api/v1/jobs/stream?job_id={job_id}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = [chunk for chunk in response.text.split("\n\n") if chunk.strip()]
    assert frames, "expected at least one SSE frame"
    assert frames[-1].startswith("event: done")
    payload = json.loads(frames[-1].split("data: ", 1)[1])
    assert payload["status"] == "succeeded"


async def test_unknown_kind_is_rejected(session: Any) -> None:
    from app.errors import Conflict

    with pytest.raises(Conflict):
        await queue.JobService(session).create(kind="nope", payload={}, user="t")
