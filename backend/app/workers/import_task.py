"""The discovery import job (T5.1).

Downloading a paper is expected to take more than the 2 s an API request may
block for (H07), so `POST /discover/fetch` only creates this job. The handler
resolves the PDF URL, downloads it from a whitelisted host, deduplicates the
bytes by sha256 (H12), creates the document and queues its parse — the import
job's result carries both ids so the UI can follow the parse.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import select

from ..db import get_session_factory
from ..discover.fetch import download, resolve
from ..discover.http import get_client
from ..ingest import storage
from ..models.orm import Document
from . import queue
from .queue import JobService
from .registry import register_handler

logger = logging.getLogger(__name__)


async def import_paper(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    source = str(payload["source"])
    ext_id = str(payload["ext_id"])
    user = str(payload.get("user") or "default")
    factory = get_session_factory()

    async with factory() as session:
        service = JobService(session)
        await service.progress(job_id, stage="resolving", progress=0.05)
        client = get_client()
        resolved = await resolve(session, source, ext_id, client)

        await service.progress(job_id, stage="downloading", progress=0.2)
        data = await download(resolved, source, client)
        sha256 = storage.sha256_bytes(data)

        existing = await session.scalar(select(Document).where(Document.sha256 == sha256))
        reused = existing is not None
        if existing is not None:
            doc = existing
            logger.info("import: bytes already in the library as %s", doc.id)
        else:
            stored = storage.write_pdf(sha256, data)
            doc = Document(
                sha256=sha256,
                title=(resolved.title or ext_id)[:400],
                arxiv_id=resolved.arxiv_id,
                status="uploading",
                file_path=str(stored),
                created_by=user,
                meta={
                    "authors": resolved.authors,
                    "year": resolved.year,
                    "abstract": resolved.abstract,
                    "doi": resolved.doi,
                    "source": source,
                    "ext_id": ext_id,
                },
            )
            session.add(doc)
            await session.flush()

        # A ready document has already been parsed; re-parsing it would burn a
        # job and could not change its blocks (H12).
        parse_job = None
        if doc.status != "ready":
            parse_job = await JobService(session).create(
                kind="parse", payload={"doc_id": doc.id}, user=user
            )
        await session.commit()
        await service.progress(
            job_id, stage="done" if parse_job is None else "queued parse", progress=0.9
        )
        doc_id = doc.id
        parse_job_id = parse_job.id if parse_job is not None else None
        pdf_url = resolved.pdf_url

    if parse_job_id is not None and not await queue.enqueue(parse_job_id):
        asyncio.create_task(queue.run_in_background(parse_job_id))

    logger.info("import job done doc_id=%s parse_job=%s", doc_id, parse_job_id)
    return {
        "doc_id": doc_id,
        "parse_job_id": parse_job_id,
        "pdf_url": pdf_url,
        "sha256": sha256,
        "reused": reused,
    }


register_handler("import", import_paper)
