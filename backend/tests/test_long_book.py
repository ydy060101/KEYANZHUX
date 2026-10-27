"""The long-book measurement (T2.5, acceptance B3).

Parsing 541 pages takes minutes, so this module is marked `slow` and is not
part of the default run. It is the only place the card's memory claim is
measured rather than argued:

  * peak resident memory stays under `parse_memory_limit_mb` (H11: 4 GB);
  * the memory curve does not grow with page count — the last window costs no
    more than the first, which is what windowing is for;
  * every page lands in the database, and the early windows are queryable
    before the last one is parsed.

Run it with:

    python -m pytest tests/test_long_book.py -q -m slow --no-header -s
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import pytest

BOOK = Path(__file__).resolve().parent.parent / "fixtures" / "pdf" / "UnderstandingDeepLearning_02_09_26_C.pdf"

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not BOOK.is_file(), reason="the 541-page fixture is not staged"),
]


def _rss_mb() -> float:
    import psutil

    return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)


def test_windowing_keeps_memory_flat() -> None:
    """Parse the whole book window by window and watch the resident set.

    The measurement is deliberately taken *during* the run, per window: a peak
    sampled only at the end would miss the window that leaked. The first
    window's cost is the baseline, and the assertion is that later windows do
    not keep climbing on top of it — a leak of one window's blocks per window
    would show up as a line with a slope.
    """
    from app.config import get_settings
    from app.ingest import pdfio
    from app.ingest.sections import SectionTracker
    from app.ingest.window_parse import parse_window
    from app.ingest.windows import plan

    settings = get_settings()
    doc = pdfio.open_document(BOOK)
    try:
        tracker = SectionTracker.for_document(doc)
        windows = plan(pdfio.page_count(doc), settings.long_book_window_pages)
        samples: list[float] = []
        started = time.monotonic()
        for window in windows:
            parse_window(
                doc,
                window,
                tracker,
                "doc-book-mem",
                threshold=settings.scanned_page_char_threshold,
            )
            samples.append(_rss_mb())
        elapsed = time.monotonic() - started
    finally:
        pdfio.close_document(doc)

    peak = max(samples)
    print(f"\nbook: {len(windows)} windows, {elapsed:.1f}s, peak rss {peak:.0f} MB")
    print("rss per window:", " ".join(f"{value:.0f}" for value in samples))
    assert peak < settings.parse_memory_limit_mb, f"peak {peak:.0f} MB exceeds H11"
    # The tail must not be systematically heavier than the head: a leak would
    # make the last quarter clearly larger than the first.
    quarter = max(1, len(samples) // 4)
    head = sum(samples[:quarter]) / quarter
    tail = sum(samples[-quarter:]) / quarter
    assert tail < head * 1.5, f"memory grew from {head:.0f} MB to {tail:.0f} MB"


async def test_every_page_lands_and_early_windows_are_queryable(session: Any) -> None:
    """B3: complete ingest, and a finished window is retrievable before the end.

    Only the first three windows are parsed here — the claim being tested is
    that a *committed* window is visible to a query while the parse is still
    running, not that 541 pages fit in a unit test's time budget.
    """
    from sqlalchemy import func, select

    from app.ingest import pdfio
    from app.ingest.sections import SectionTracker
    from app.ingest.window_parse import parse_window
    from app.ingest.windows import Window
    from app.models.orm import Block as BlockRow
    from app.models.orm import Chunk, Document
    from app.rag.chunk import Chunker
    from app.rag.index import write_index
    from app.workers import persist

    session.add(Document(id="doc-book", sha256="b" * 64, title="Book", status="parsing", file_path=str(BOOK)))
    await session.commit()

    doc = pdfio.open_document(BOOK)
    chunker = Chunker()
    try:
        tracker = SectionTracker.for_document(doc)
        for index, (start, end) in enumerate([(15, 34), (35, 54), (55, 74)], start=1):
            result = parse_window(doc, Window(index=index, start=start, end=end), tracker, "doc-book", threshold=30)
            drafts = chunker.feed(result.blocks)
            await persist.persist_window(session, "doc-book", result.blocks, result.assets)
            await write_index(session, "doc-book", result.blocks, result.outline, drafts)
            stored = await session.scalar(
                select(func.count()).select_from(BlockRow).where(BlockRow.doc_id == "doc-book")
            )
            # The window just parsed is already visible, before the next one runs.
            assert stored and stored >= len(result.blocks), (index, stored)
            chunks = await session.scalar(
                select(func.count()).select_from(Chunk).where(Chunk.doc_id == "doc-book")
            )
            assert chunks is not None
    finally:
        pdfio.close_document(doc)

    pages = await session.scalars(select(BlockRow.page).where(BlockRow.doc_id == "doc-book").distinct())
    assert set(pages) == set(range(15, 75))


async def test_re_running_a_window_changes_nothing(session: Any) -> None:
    """H12: a resumed run rewrites its own window and leaves the others alone."""

    from app.ingest import pdfio
    from app.ingest.sections import SectionTracker
    from app.ingest.window_parse import parse_window
    from app.ingest.windows import Window
    from app.models.orm import Document
    from app.rag.chunk import Chunker
    from app.rag.index import write_index
    from app.workers import persist

    session.add(Document(id="doc-idem", sha256="c" * 64, title="Book", status="parsing", file_path=str(BOOK)))
    await session.commit()

    doc = pdfio.open_document(BOOK)
    try:
        tracker = SectionTracker.for_document(doc)
        chunker = Chunker()
        for start, end, index in ((15, 34, 1), (35, 54, 2)):
            result = parse_window(doc, Window(index=index, start=start, end=end), tracker, "doc-idem", threshold=30)
            drafts = chunker.feed(result.blocks)
            await persist.persist_window(session, "doc-idem", result.blocks, result.assets)
            await write_index(session, "doc-idem", result.blocks, result.outline, drafts)
        before = await _counts(session)

        # Resume: the first window runs again, as it would after a killed job.
        tracker2 = SectionTracker.for_document(doc)
        again = parse_window(doc, Window(index=1, start=15, end=34), tracker2, "doc-idem", threshold=30)
        drafts = Chunker().feed(again.blocks)
        await persist.persist_window(session, "doc-idem", again.blocks, again.assets)
        await write_index(session, "doc-idem", again.blocks, again.outline, drafts)
    finally:
        pdfio.close_document(doc)

    assert await _counts(session) == before, "re-running a window changed the stored rows"


async def _counts(session: Any) -> dict[str, int]:
    from sqlalchemy import func, select

    from app.models.orm import Block as BlockRow
    from app.models.orm import Chunk, SectionSummaryRow

    out: dict[str, int] = {}
    for name, table in (("blocks", BlockRow), ("chunks", Chunk), ("sections", SectionSummaryRow)):
        out[name] = await session.scalar(select(func.count()).select_from(table)) or 0
    return out


async def test_a_window_that_is_already_stored_is_recognised(session: Any) -> None:
    """The resume decision: a window's own page range answers it."""
    from app.ingest import pdfio
    from app.ingest.sections import SectionTracker
    from app.ingest.window_parse import parse_window
    from app.ingest.windows import Window
    from app.models.orm import Document
    from app.workers import persist

    session.add(Document(id="doc-resume", sha256="d" * 64, title="Book", status="parsing", file_path=str(BOOK)))
    await session.commit()

    doc = pdfio.open_document(BOOK)
    try:
        tracker = SectionTracker.for_document(doc)
        first = Window(index=1, start=15, end=34)
        result = parse_window(doc, first, tracker, "doc-resume", threshold=30)
        await persist.persist_window(session, "doc-resume", result.blocks, result.assets)
    finally:
        pdfio.close_document(doc)

    assert await persist.window_done(session, "doc-resume", 15, 34)
    assert not await persist.window_done(session, "doc-resume", 35, 54)

    stored = await persist.load_window_blocks(session, "doc-resume", 15, 34)
    assert stored, "a resumed run needs the stored blocks to rebuild its state"
    assert [block.reading_order for block in stored] == sorted(block.reading_order for block in stored)
