"""End-to-end: parse the 541-page book through the real job handler.

The unit tests exercise the windowed parse, the persist layer and the index
separately. This script runs the actual `parse_document` handler against the
real file and the real database, and reports what B3 asks for:

  * every page landed;
  * progress advanced per window;
  * peak memory stayed under H11's 4 GB;
  * a window's chunks were queryable before the parse finished.

Run from `backend/`:

    .venv/Scripts/python.exe -I tools/check_long_book.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from redis.asyncio import Redis  # noqa: E402
from redis.asyncio.client import PubSub as RedisPubSub  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402

from app import db  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.ingest import storage  # noqa: E402
from app.ingest.windows import plan  # noqa: E402
from app.models.orm import Block as BlockRow  # noqa: E402
from app.models.orm import Chunk, Document, Job, ReferenceRow, SectionSummaryRow  # noqa: E402
from app.workers import queue, register_all  # noqa: E402

BOOK = BACKEND / "fixtures" / "pdf" / "UnderstandingDeepLearning_02_09_26_C.pdf"


async def main() -> int:
    register_all()
    factory = db.get_session_factory()
    data = BOOK.read_bytes()
    sha = storage.sha256_bytes(data)
    path = storage.write_pdf(sha, data)

    async with factory() as session:
        doc = await session.scalar(select(Document).where(Document.sha256 == sha))
        if doc is None:
            doc = Document(sha256=sha, title="Understanding Deep Learning", status="uploading", file_path=str(path))
            session.add(doc)
        else:
            # A previous run left this document parsed. The check measures a
            # *fresh* parse — resume behaviour is covered by the unit tests —
            # so the stored rows are cleared and the document starts over.
            from app.workers import persist

            doc.file_path = str(path)
            doc.status = "uploading"
            await session.flush()
            await persist.clear_document(session, doc.id)
            await session.execute(text("DELETE FROM chunks WHERE doc_id = :id"), {"id": doc.id})
            await session.execute(
                text("DELETE FROM section_summaries WHERE doc_id = :id"), {"id": doc.id}
            )
        await session.flush()
        doc_id = doc.id
        job = await queue.JobService(session).create(kind="parse", payload={"doc_id": doc_id}, user="default")
        await session.commit()
        job_id = job.id

    print(f"doc {doc_id} job {job_id}: parsing {BOOK.name} ({BOOK.stat().st_size / 1e6:.1f} MB)")

    stages: list[tuple[float, str, float]] = []
    events: list[str] = []
    stop = asyncio.Event()

    async def watch_events(pubsub: RedisPubSub) -> None:
        """Record every stage the worker publishes, not a sample of them.

        The worker publishes each window's progress to `job:{id}` (the same
        channel the frontend's SSE relay reads). Polling the `jobs` table
        instead drops windows whenever a poll happens to take longer than the
        gap between two commits, which is a property of this script and not of
        the parse — so the count comes from the event stream.
        """
        while True:
            timeout = 0.0 if stop.is_set() else 1.0
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=timeout)
            if message is None:
                if stop.is_set():
                    return
                continue
            payload = json.loads(message["data"])
            stage = payload.get("stage") or ""
            if stage.startswith("window"):
                events.append(stage)
                stages.append((time.monotonic(), stage, float(payload.get("progress") or 0.0)))

    async def watch_memory() -> None:
        import psutil

        process = psutil.Process()
        peak = 0.0
        while not stop.is_set():
            peak = max(peak, process.memory_info().rss / (1024 * 1024))
            stages.append((time.monotonic(), "rss", peak))
            await asyncio.sleep(0.5)
        stages.append((time.monotonic(), "peak_rss_mb", peak))

    async def watch_visibility() -> None:
        """B3: a window that has committed must be queryable before the parse ends."""
        while not stop.is_set():
            async with factory() as session:
                stored = await session.scalar(
                    select(func.count()).select_from(BlockRow).where(BlockRow.doc_id == doc_id)
                )
                chunks = await session.scalar(
                    select(func.count()).select_from(Chunk).where(Chunk.doc_id == doc_id)
                )
            stages.append((time.monotonic(), f"  stored blocks={stored} chunks={chunks}", 0.0))
            await asyncio.sleep(0.5)

    started = time.monotonic()
    # Subscribed before the parse begins, so no window's event can be missed.
    client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    pubsub = client.pubsub()
    await pubsub.subscribe(queue.channel(job_id))
    watchers = [
        asyncio.create_task(watch_events(pubsub)),
        asyncio.create_task(watch_memory()),
        asyncio.create_task(watch_visibility()),
    ]
    try:
        await queue.execute(job_id)
    finally:
        stop.set()
        await asyncio.gather(*watchers)
        await pubsub.aclose()
        await client.aclose()
    elapsed = time.monotonic() - started

    async with factory() as session:
        row = await session.get(Job, job_id)
        doc = await session.get(Document, doc_id)
        blocks = await session.scalar(select(func.count()).select_from(BlockRow).where(BlockRow.doc_id == doc_id))
        pages = await session.scalar(
            select(func.count(func.distinct(BlockRow.page))).where(BlockRow.doc_id == doc_id)
        )
        chunks = await session.scalar(select(func.count()).select_from(Chunk).where(Chunk.doc_id == doc_id))
        sections = await session.scalar(
            select(func.count()).select_from(SectionSummaryRow).where(SectionSummaryRow.doc_id == doc_id)
        )
        headings = await session.scalar(
            select(func.count())
            .select_from(BlockRow)
            .where(BlockRow.doc_id == doc_id, BlockRow.type == "heading")
        )
        references = await session.scalar(
            select(func.count()).select_from(ReferenceRow).where(ReferenceRow.doc_id == doc_id)
        )
        assert row is not None and doc is not None
        print(f"\njob: {row.status} stage={row.stage} progress={row.progress:.2f} error={row.error}")
        print(f"doc: status={doc.status} pages={doc.page_count} source_kind={doc.source_kind}")
        print(
            f"stored: blocks={blocks} pages={pages} chunks={chunks} "
            f"sections={sections} headings={headings} references={references}"
        )
        print(f"elapsed {elapsed:.1f}s")

    windows = [item for item in stages if item[1].startswith("window")]
    print(f"\nwindow events ({len(windows)}):")
    for _, stage, progress in windows[:6] + windows[-3:]:
        print(f"  {stage:>16}  {progress:.3f}")
    stored = [item[1] for item in stages if item[1].strip().startswith("stored")]
    print("early visibility:", stored[:3])
    peak = next((value for _, name, value in stages if name == "peak_rss_mb"), 0.0)
    print(f"peak rss {peak:.0f} MB (H11 limit {get_settings().parse_memory_limit_mb} MB)")

    # Every window publishes one event; the plan says how many there should be.
    # Both are printed so a missing window cannot hide behind a sampling rate.
    planned = plan(541, get_settings().long_book_window_pages)
    reported = {int(stage.split("/")[0].split()[-1]) for stage in events if "/" in stage}
    print(f"windows planned: {len(planned)}; windows reported: {len(reported)}")

    # B3 says "完整入库". Four pages of this book carry no text layer, no
    # image and no drawing — they are blank in the source, not lost here — so
    # the criterion is every page that has content, and the blank ones are
    # reported rather than counted as a failure.
    blank = blank_pages()
    ok = (
        row.status == "succeeded"
        and doc.status == "ready"
        and pages == 541 - len(blank)
        and peak < get_settings().parse_memory_limit_mb
        and len(planned) == len(reported)
        # The bibliography is document-wide; a window-aligned extraction used
        # to miss it entirely on this book (T2.6).
        and bool(references)
    )
    print(f"blank pages in the source: {blank} ({len(blank)} of 541)")
    print("\nB3:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def blank_pages() -> list[int]:
    """Pages with no text layer, no image and no drawing — empty in the source."""
    from app.ingest import pdfio

    doc = pdfio.open_document(BOOK)
    try:
        return [
            index + 1
            for index in range(pdfio.page_count(doc))
            if not pdfio.page_text(doc[index]).strip()
            and not pdfio.image_boxes(doc[index])
            and not pdfio.drawing_boxes(doc[index])
        ]
    finally:
        pdfio.close_document(doc)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
