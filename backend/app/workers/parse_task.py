"""The parse job: PDF → DocumentModel → database (01 §7).

Stages 1-3 and 5 land here (T1.3); later cards add figures, formulas, OCR and
long-book windowing on top of the same handler.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session_factory
from ..ingest.metadata import extract_meta_llm
from ..ingest.parser import detect_source_kind, extract_blocks, probe_pages
from ..ingest.pdfio import close_document, open_document, page_count
from ..llm.gateway import get_gateway
from ..models.orm import Block as BlockRow
from ..models.orm import CitationRow, Document, ReferenceRow
from ..models.schemas import DocumentModel
from .queue import JobService
from .registry import register_handler

logger = logging.getLogger(__name__)


async def parse_document(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    doc_id = str(payload["doc_id"])
    factory = get_session_factory()

    async with factory() as session:
        doc = await session.get(Document, doc_id)
        if doc is None:
            raise ValueError(f"文档不存在：{doc_id}")
        path = Path(doc.file_path)
        await JobService(session).progress(job_id, stage="probe", progress=0.05)

    settings = get_settings()
    doc_handle = open_document(path)
    try:
        pages = probe_pages(doc_handle, settings.scanned_page_char_threshold)
        async with factory() as session:
            await JobService(session).progress(job_id, stage="layout", progress=0.2)

        blocks, outline = extract_blocks(doc_handle, pages, doc_id)
        async with factory() as session:
            await JobService(session).progress(job_id, stage="metadata", progress=0.45)

        meta = await extract_meta_llm(doc_handle, blocks, doc_id, get_gateway())
        total_pages = page_count(doc_handle)
    except Exception:
        async with factory() as session:
            doc = await session.get(Document, doc_id)
            if doc is not None:
                doc.status = "failed"
                doc.parse_error = "解析失败"
        raise
    finally:
        close_document(doc_handle)

    model = DocumentModel(
        doc_id=doc_id,
        sha256="",
        page_count=total_pages,
        source_kind=detect_source_kind(pages, settings.scanned_page_char_threshold),
        meta=meta,
        outline=outline,
        blocks=blocks,
    )

    async with factory() as session:
        await JobService(session).progress(job_id, stage="persist", progress=0.8)
        await persist_parse(session, model)

    logger.info("parsed doc_id=%s blocks=%d pages=%d", doc_id, len(blocks), total_pages)
    return {"doc_id": doc_id, "blocks": len(blocks), "pages": total_pages}


async def persist_parse(session: AsyncSession, model: DocumentModel) -> None:
    """Replace a document's parsed rows in one transaction (idempotent, H12)."""
    doc = await session.get(Document, model.doc_id)
    if doc is None:
        raise ValueError(f"文档不存在：{model.doc_id}")

    await session.execute(delete(BlockRow).where(BlockRow.doc_id == model.doc_id))
    await session.execute(delete(ReferenceRow).where(ReferenceRow.doc_id == model.doc_id))
    await session.execute(delete(CitationRow).where(CitationRow.doc_id == model.doc_id))

    for block in model.blocks:
        session.add(
            BlockRow(
                doc_id=model.doc_id,
                id=block.id,
                type=block.type,
                page=block.page,
                bbox=block.bbox,
                reading_order=block.reading_order,
                section_id=block.section_id,
                text=block.text,
                confidence=block.confidence,
            )
        )
    doc.title = model.meta.title
    doc.page_count = model.page_count
    doc.source_kind = model.source_kind
    doc.status = "ready"
    await session.flush()


register_handler("parse", parse_document)
