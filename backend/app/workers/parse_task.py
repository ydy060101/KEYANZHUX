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
from ..ingest.parser import detect_arxiv_id, detect_source_kind, extract_blocks, probe_pages
from ..ingest.pdfio import close_document, open_document, page_count
from ..llm.gateway import get_gateway
from ..models.orm import AssetRow, CitationRow, Document, ReferenceRow
from ..models.orm import Block as BlockRow
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
        stored_sha = doc.sha256
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
        first_text = blocks[0].text if blocks else ""
        detected_arxiv, detected_version = detect_arxiv_id(path.name, first_text)
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
        sha256=stored_sha,
        page_count=total_pages,
        source_kind=detect_source_kind(pages, settings.scanned_page_char_threshold),
        meta=meta,
        outline=outline,
        blocks=blocks,
        arxiv_id=detected_arxiv,
        version=detected_version,
    )

    async with factory() as session:
        await JobService(session).progress(job_id, stage="persist", progress=0.8)
        await persist_parse(session, model)
        await _store_fingerprint(session, model)

    logger.info("parsed doc_id=%s blocks=%d pages=%d", doc_id, len(blocks), total_pages)
    return {"doc_id": doc_id, "blocks": len(blocks), "pages": total_pages}


async def _store_fingerprint(session: AsyncSession, model: DocumentModel) -> None:
    """Index the fingerprint L3 dedup compares against on the next upload."""
    from ..dedup.service import Candidate, store_fingerprint

    body = "\n".join(block.text for block in model.blocks if block.type != "reference")[:8000]
    await store_fingerprint(
        session,
        model.doc_id,
        Candidate(
            sha256=model.sha256,
            arxiv_id=model.arxiv_id,
            version=model.version,
            title=model.meta.title,
            abstract=model.meta.abstract.text if model.meta.abstract else "",
            body=body,
        ),
    )


async def persist_parse(session: AsyncSession, model: DocumentModel) -> None:
    """Replace a document's parsed rows in one transaction (idempotent, H12)."""
    doc = await session.get(Document, model.doc_id)
    if doc is None:
        raise ValueError(f"文档不存在：{model.doc_id}")

    await session.execute(delete(BlockRow).where(BlockRow.doc_id == model.doc_id))
    await session.execute(delete(ReferenceRow).where(ReferenceRow.doc_id == model.doc_id))
    await session.execute(delete(CitationRow).where(CitationRow.doc_id == model.doc_id))
    await session.execute(delete(AssetRow).where(AssetRow.doc_id == model.doc_id))

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
    for reference in model.references:
        session.add(
            ReferenceRow(
                id=f"{model.doc_id}:{reference.id}",
                doc_id=model.doc_id,
                index=reference.index,
                raw=reference.raw,
                title=reference.title,
                authors=reference.authors,
                year=reference.year,
                doi=reference.doi,
                arxiv_id=reference.arxiv_id,
                block_id=reference.block_id,
                bbox=reference.bbox,
            )
        )
    for citation in model.citations:
        session.add(
            CitationRow(
                id=f"{model.doc_id}:{citation.id}",
                doc_id=model.doc_id,
                marker=citation.marker,
                ref_ids=citation.ref_ids,
                block_id=citation.block_id,
                bbox=citation.bbox,
                method=citation.method,
            )
        )
    for asset in model.assets:
        session.add(
            AssetRow(
                id=f"{model.doc_id}:{asset.id}",
                doc_id=model.doc_id,
                kind=asset.kind,
                page=asset.page,
                bbox=asset.bbox,
                path=asset.path,
            )
        )
    doc.title = model.meta.title or doc.title
    doc.arxiv_id = model.arxiv_id or doc.arxiv_id
    doc.version = model.version or doc.version
    doc.page_count = model.page_count
    doc.source_kind = model.source_kind
    doc.status = "ready"
    await session.flush()
    # This function owns its transaction: closing the session without a commit
    # would silently discard every row above while the job still reports success.
    await session.commit()


register_handler("parse", parse_document)
