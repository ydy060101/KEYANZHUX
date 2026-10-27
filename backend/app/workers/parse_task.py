"""The parse job: PDF → DocumentModel → database (01 §7).

Stages 1-3 and 5 land here (T1.3); T2.4 added OCR, T2.5 the windowed path for
long documents.

Two paths, one document model:

  * a short paper is parsed in one pass — 15 pages do not need per-window
    transactions, and a single pass keeps references and citations computed
    over the whole block list at once;
  * a long book goes window by window (`windows.parse_window`), persisting and
    indexing each window as it finishes, so the pages already done are
    readable and retrievable while the rest parses (H07, H11, T2.5).

Which path runs is decided by page count against `long_book_window_pages`, so
it is a config value, not a special case in the code.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session_factory
from ..dedup.service import Candidate
from ..ingest import storage
from ..ingest.assets import extract_assets
from ..ingest.citations import build_citations
from ..ingest.metadata import extract_meta_llm
from ..ingest.parser import (
    PageStats,
    detect_arxiv_id,
    detect_source_kind,
    extract_blocks,
    probe_pages,
)
from ..ingest.pdfio import close_document, open_document, page_count
from ..ingest.references import extract_references
from ..ingest.sections import SectionTracker
from ..ingest.window_parse import parse_window
from ..ingest.windows import Window, is_long, plan
from ..llm.gateway import get_gateway
from ..models.orm import Document
from ..models.schemas import Block, DocumentModel
from ..rag.chunk import Chunker
from ..rag.index import write_index
from . import persist
from .queue import JobService
from .registry import register_handler

logger = logging.getLogger(__name__)

# Progress the job reports, as fractions of the whole parse. Parsing pages is
# the bulk of the work; the fixed stages are what happens around it.
_PROBE = 0.02
_METADATA = 0.06
_INDEX = 0.97
_DONE = 0.99


async def parse_document(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    doc_id = str(payload["doc_id"])
    factory = get_session_factory()

    async with factory() as session:
        doc = await session.get(Document, doc_id)
        if doc is None:
            raise ValueError(f"文档不存在：{doc_id}")
        path = storage.resolve(doc.file_path)
        stored_sha = doc.sha256
        await JobService(session).progress(job_id, stage="probe", progress=_PROBE)

    settings = get_settings()
    doc_handle = open_document(path)
    try:
        pages = probe_pages(doc_handle, settings.scanned_page_char_threshold)
        total_pages = page_count(doc_handle)
        async with factory() as session:
            await JobService(session).progress(job_id, stage="layout", progress=0.1)

        if is_long(total_pages, settings.long_book_window_pages):
            return await _parse_long(
                job_id, doc_id, doc_handle, path, pages, total_pages, stored_sha
            )
        return await _parse_short(job_id, doc_id, doc_handle, path, pages, total_pages, stored_sha)
    except Exception:
        await _mark_failed(doc_id, "解析失败")
        raise
    finally:
        close_document(doc_handle)


async def _parse_short(
    job_id: str,
    doc_id: str,
    doc_handle: Any,
    path: Any,
    pages: list[PageStats],
    total_pages: int,
    stored_sha: str,
) -> dict[str, Any]:
    """The single-pass path: the whole paper is in memory anyway."""
    settings = get_settings()
    factory = get_session_factory()
    blocks, outline = extract_blocks(
        doc_handle, pages, doc_id, threshold=settings.scanned_page_char_threshold
    )
    async with factory() as session:
        await JobService(session).progress(job_id, stage="metadata", progress=0.3)
    meta = await extract_meta_llm(doc_handle, blocks, doc_id, get_gateway())
    first_text = blocks[0].text if blocks else ""
    detected_arxiv, detected_version = detect_arxiv_id(path.name, first_text)
    references = extract_references(blocks, doc_id)
    citations, coverage = build_citations(doc_handle, blocks, references)
    async with factory() as session:
        await JobService(session).progress(job_id, stage="assets", progress=0.6)
    assets = extract_assets(doc_handle, blocks, doc_id)

    model = DocumentModel(
        doc_id=doc_id,
        sha256=stored_sha,
        page_count=total_pages,
        source_kind=detect_source_kind(pages, settings.scanned_page_char_threshold),
        meta=meta,
        outline=outline,
        blocks=blocks,
        references=references,
        citations=citations,
        assets=assets,
        arxiv_id=detected_arxiv,
        version=detected_version,
    )

    async with factory() as session:
        await JobService(session).progress(job_id, stage="persist", progress=0.85)
        await persist.clear_document(session, doc_id)
        await persist.persist_parse(session, model)
        await _index_all(session, model)
        await _store_fingerprint(session, model)

    result = _result(model, coverage)
    await _maybe_recheck(doc_id, model, result)
    _log_result(doc_id, model, coverage)
    return result


async def _parse_long(
    job_id: str,
    doc_id: str,
    doc_handle: Any,
    path: Any,
    pages: list[PageStats],
    total_pages: int,
    stored_sha: str,
) -> dict[str, Any]:
    """The windowed path: parse, persist and index one window at a time."""
    settings = get_settings()
    factory = get_session_factory()
    windows = plan(total_pages, settings.long_book_window_pages)
    tracker = SectionTracker.for_document(doc_handle)
    sizes: dict[str, float] = {}
    chunker = Chunker(
        target=settings.chunk_target_tokens,
        minimum=settings.chunk_min_tokens,
        maximum=settings.chunk_max_tokens,
        overlap_ratio=settings.chunk_overlap_ratio,
    )

    total_blocks = total_references = total_citations = total_assets = 0
    coverage: Any = None
    # Metadata comes from the opening pages, which are in the first window;
    # holding the whole book to read them again at the end would defeat the
    # point of windowing (H11).
    first_blocks: list[Block] = []

    # Resume (H12): a window whose rows are already stored is not parsed
    # again. The tracker and the chunker are in-memory state, so they are
    # rebuilt by replaying the stored blocks of the windows being skipped —
    # without that, the first window parsed after a resume would assign
    # sections and cut chunks as if the book began there.
    resumed_from = 0
    async with factory() as session:
        for window in windows:
            if not await persist.window_done(session, doc_id, window.start, window.end):
                break
            stored = await persist.load_window_blocks(session, doc_id, window.start, window.end)
            tracker.assign(stored, sizes)
            chunker.feed(stored)
            resumed_from = window.index
        if resumed_from == 0:
            await persist.clear_document(session, doc_id)
        await JobService(session).progress(
            job_id,
            stage="windows",
            progress=_window_progress(windows[max(0, resumed_from - 1)], len(windows)),
            windows_done=resumed_from,
            windows_total=len(windows),
        )
    if resumed_from:
        logger.info("resuming %s after %d stored windows", doc_id, resumed_from)

    for window in windows[resumed_from:]:
        result = parse_window(
            doc_handle,
            window,
            tracker,
            doc_id,
            threshold=settings.scanned_page_char_threshold,
            sizes=sizes,
            with_references=window is windows[-1],
        )
        if window.index == 1:
            first_blocks = list(result.blocks)
        drafts = chunker.feed(result.blocks)
        async with factory() as session:
            await persist.persist_window(
                session,
                doc_id,
                result.blocks,
                result.assets,
                first_window=window.index == 1,
                last_window=window is windows[-1],
                references=result.references,
                citations=result.citations,
            )
            await write_index(session, doc_id, result.blocks, result.outline, drafts)
            await JobService(session).progress(
                job_id,
                stage=f"window {window.index}/{len(windows)}",
                progress=_window_progress(window, len(windows)),
                windows_done=window.index,
                windows_total=len(windows),
                pages_done=window.end,
            )
        total_blocks += len(result.blocks)
        total_assets += len(result.assets)
        total_references += len(result.references)
        total_citations += len(result.citations)
        if result.coverage is not None:
            coverage = result.coverage
        logger.info(
            "window %s done: blocks=%d assets=%d (rss kept flat by dropping it)",
            window.label,
            len(result.blocks),
            len(result.assets),
        )
        # The window's objects go out of scope here; nothing from it is kept.
        del result

    async with factory() as session:
        await JobService(session).progress(job_id, stage="finish", progress=_DONE)
        final = chunker.flush()
        if final:
            await write_index(session, doc_id, [], tracker.outline(), final)
        doc = await session.get(Document, doc_id)
        if doc is None:
            raise ValueError(f"文档不存在：{doc_id}")
        meta = await extract_meta_llm(doc_handle, first_blocks, doc_id, get_gateway())
        doc.title = meta.title or doc.title
        doc.page_count = total_pages
        doc.source_kind = detect_source_kind(pages, settings.scanned_page_char_threshold)
        doc.status = "ready"
        await session.commit()

    result_payload: dict[str, Any] = {
        "doc_id": doc_id,
        "blocks": total_blocks,
        "pages": total_pages,
        "references": total_references,
        "citations": total_citations,
        "assets": total_assets,
        "windows": len(windows),
        "coverage": coverage.as_dict() if coverage is not None else {},
    }
    logger.info(
        "parsed long doc_id=%s windows=%d blocks=%d pages=%d",
        doc_id,
        len(windows),
        total_blocks,
        total_pages,
    )
    return result_payload


def _window_progress(window: Window, total: int) -> float:
    """Parsing is 10%–97% of the job; each window owns an equal slice of it."""
    span = _INDEX - 0.1
    return 0.1 + span * window.index / max(1, total)


async def _index_all(session: AsyncSession, model: DocumentModel) -> None:
    """Build the two-level index for a short document in one pass."""
    chunker = Chunker()
    drafts = chunker.feed(model.blocks) + chunker.flush()
    await write_index(session, model.doc_id, model.blocks, model.outline, drafts)
    await session.commit()


def _result(model: DocumentModel, coverage: Any) -> dict[str, Any]:
    return {
        "doc_id": model.doc_id,
        "blocks": len(model.blocks),
        "pages": model.page_count,
        "references": len(model.references),
        "citations": len(model.citations),
        "assets": len(model.assets),
        "coverage": coverage.as_dict(),
    }


def _log_result(doc_id: str, model: DocumentModel, coverage: Any) -> None:
    logger.info(
        "parsed doc_id=%s blocks=%d pages=%d citations=%d cited=%d/%d",
        doc_id,
        len(model.blocks),
        model.page_count,
        len(model.citations),
        coverage.cited,
        coverage.references,
    )


async def _mark_failed(doc_id: str, message: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        doc = await session.get(Document, doc_id)
        if doc is not None:
            doc.status = "failed"
            doc.parse_error = message
            await session.commit()


async def _maybe_recheck(doc_id: str, model: DocumentModel, result: dict[str, Any]) -> None:
    """A scan has no text at upload time, so §8 re-checks after OCR (T2.4)."""
    if model.source_kind not in {"scanned", "mixed"}:
        return
    factory = get_session_factory()
    async with factory() as session:
        await _recheck_duplicate(session, model, result)


async def _store_fingerprint(session: AsyncSession, model: DocumentModel) -> None:
    """Index the fingerprint L3 dedup compares against on the next upload."""
    from ..dedup.service import store_fingerprint

    await store_fingerprint(session, model.doc_id, _candidate(model))


def _candidate(model: DocumentModel) -> Candidate:
    """What L3 sees of a parsed document: title, abstract and opening text."""
    body = "\n".join(block.text for block in model.blocks if block.type != "reference")[:8000]
    return Candidate(
        sha256=model.sha256,
        arxiv_id=model.arxiv_id,
        version=model.version,
        title=model.meta.title,
        abstract=model.meta.abstract.text if model.meta.abstract else "",
        body=body,
    )


async def _recheck_duplicate(session: AsyncSession, model: DocumentModel, result: dict[str, Any]) -> None:
    """Re-run L3 once OCR has produced text (01 §8, T2.4).

    The upload path can only judge a scan by its filename, which §8 forbids, so
    the parse job judges it again now that the pages carry text. The finding
    goes into the job result, which the client already polls.
    """
    from ..dedup.service import check

    candidate = _candidate(model)
    if not candidate.body.strip():
        return
    found = await check(session, candidate, exclude_doc_id=model.doc_id, load_model=False)
    if found is None:
        return
    result["dedup"] = found.model_dump()
    logger.info("post-OCR dedup for %s: %s vs %s", model.doc_id, found.level, found.matched_doc_id)


register_handler("parse", parse_document)
