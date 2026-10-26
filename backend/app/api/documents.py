"""Document CRUD, upload and PDF streaming (01 §5.1, T1.2)."""

from __future__ import annotations

import asyncio
import mimetypes
import re
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, Header, Query, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import SessionDep, UserIdDep
from ..ingest import storage
from ..ingest.validate import validate_upload
from ..models.orm import Block as BlockRow
from ..models.orm import Document, ReferenceRow
from ..models.schemas import BlockType
from ..workers import queue

router = APIRouter(tags=["documents"])

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


def _document_payload(doc: Document, stats: dict[str, int] | None = None) -> dict[str, Any]:
    return {
        "id": doc.id,
        "sha256": doc.sha256,
        "arxiv_id": doc.arxiv_id,
        "version": doc.version,
        "title": doc.title,
        "status": doc.status,
        "source_kind": doc.source_kind,
        "page_count": doc.page_count,
        "tags": list(doc.tags or []),
        "created_at": doc.created_at.isoformat() if isinstance(doc.created_at, datetime) else doc.created_at,
        "stats": stats or {},
    }


async def _stats(session: AsyncSession, doc_id: str) -> dict[str, int]:
    rows = await session.execute(
        select(BlockRow.type, func.count()).where(BlockRow.doc_id == doc_id).group_by(BlockRow.type)
    )
    counts: dict[BlockType, int] = {row[0]: row[1] for row in rows}
    references = await session.scalar(
        select(func.count()).select_from(ReferenceRow).where(ReferenceRow.doc_id == doc_id)
    )
    return {
        "blocks": sum(counts.values()),
        "figures": counts.get("figure", 0),
        "tables": counts.get("table", 0),
        "formulas": counts.get("formula", 0),
        "references": references or 0,
    }


@router.get("/documents")
async def list_documents(
    session: SessionDep,
    user: UserIdDep,
    query: Annotated[str | None, Query()] = None,
    tag: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 20,
) -> dict[str, Any]:
    stmt = select(Document).where(Document.created_by == user)
    if query:
        stmt = stmt.where(Document.title.ilike(f"%{query}%"))
    if status:
        stmt = stmt.where(Document.status == status)
    if tag:
        stmt = stmt.where(Document.tags.contains([tag]))
    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = await session.scalars(
        stmt.order_by(Document.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    items = [_document_payload(doc) for doc in rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/documents", status_code=202)
async def upload_documents(
    session: SessionDep,
    user: UserIdDep,
    files: Annotated[list[UploadFile], File()],
) -> list[dict[str, Any]]:
    """Accept one or more PDFs. Re-uploading the same bytes returns the same doc.

    The whole request is one transaction, so a rejected file leaves no partial
    rows behind.
    """
    results: list[dict[str, Any]] = []
    for file in files:
        filename, data = await validate_upload(file)
        sha256 = storage.sha256_bytes(data)

        existing = await session.scalar(select(Document).where(Document.sha256 == sha256))
        if existing is not None:
            # H12: the same bytes are the same document, whatever the filename.
            job = await queue.JobService(session).create(
                kind="parse", payload={"doc_id": existing.id}, user=user
            )
            results.append(
                {
                    "upload_id": sha256[:16],
                    "doc_id": existing.id,
                    "job_id": job.id,
                    "status": existing.status,
                    "dedup": None,
                }
            )
            continue

        stored = storage.write_pdf(sha256, data)
        doc = Document(
            sha256=sha256,
            title=Path(filename).stem,
            status="uploading",
            file_path=str(stored),
            created_by=user,
        )
        session.add(doc)
        await session.flush()

        job = await queue.JobService(session).create(kind="parse", payload={"doc_id": doc.id}, user=user)
        results.append(
            {
                "upload_id": sha256[:16],
                "doc_id": doc.id,
                "job_id": job.id,
                "status": doc.status,
                "dedup": None,
            }
        )

    await session.commit()
    for item in results:
        if not await queue.enqueue(item["job_id"]):
            import asyncio

            asyncio.create_task(queue.run_in_background(item["job_id"]))
    return results


@router.get("/documents/{doc_id}")
async def get_document(doc_id: str, session: SessionDep) -> dict[str, Any]:
    doc = await _load(session, doc_id)
    return _document_payload(doc, await _stats(session, doc_id))


@router.patch("/documents/{doc_id}")
async def patch_document(doc_id: str, body: dict[str, Any], session: SessionDep) -> dict[str, Any]:
    doc = await _load(session, doc_id)
    if isinstance(body.get("title"), str) and body["title"].strip():
        doc.title = body["title"].strip()[:400]
    if isinstance(body.get("tags"), list):
        doc.tags = [str(tag)[:64] for tag in body["tags"] if str(tag).strip()][:32]
    await session.commit()
    return _document_payload(doc)


@router.delete("/documents/{doc_id}", status_code=204)
async def delete_document(doc_id: str, session: SessionDep) -> Response:
    doc = await _load(session, doc_id)
    file_path = doc.file_path
    await session.delete(doc)
    await session.commit()
    # Rows cascade; files are removed after the commit so a failure cannot
    # leave a document pointing at deleted bytes.
    storage.remove_document(doc_id, file_path)
    return Response(status_code=204)


@router.get("/documents/{doc_id}/file")
async def stream_file(
    doc_id: str,
    session: SessionDep,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> Response:
    doc = await _load(session, doc_id)
    path = Path(doc.file_path)
    # A PDF is streamed in 64 KB pieces, so the event loop only ever waits on
    # short reads rather than one blocking full-file read.
    if not await asyncio.to_thread(path.is_file):
        from ..errors import NotFound

        raise NotFound("PDF 文件已丢失", detail={"doc_id": doc_id})

    size = (await asyncio.to_thread(path.stat)).st_size
    media_type = mimetypes.guess_type(path.name)[0] or "application/pdf"

    if range_header:
        match = _RANGE_RE.fullmatch(range_header.strip())
        if match is None:
            from ..errors import InvalidRequest

            raise InvalidRequest("Range 头格式不正确", detail={"range": range_header})
        start_raw, end_raw = match.group(1), match.group(2)
        start = int(start_raw) if start_raw else 0
        end = int(end_raw) if end_raw else size - 1
        if start >= size or start > end:
            return Response(
                status_code=416,
                headers={"Content-Range": f"bytes */{size}"},
            )
        end = min(end, size - 1)
        chunk = await asyncio.to_thread(_read_range, path, start, end - start + 1)
        return Response(
            content=chunk,
            status_code=206,
            media_type=media_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(chunk)),
            },
        )

    return StreamingResponse(
        _iter_file(path),
        media_type=media_type,
        headers={"Accept-Ranges": "bytes", "Content-Length": str(size)},
    )


def _read_range(path: Path, offset: int, length: int) -> bytes:
    with path.open("rb") as fh:
        fh.seek(offset)
        return fh.read(length)


async def _iter_file(path: Path) -> AsyncIterator[bytes]:
    """Yield 64 KB pieces, reading on a worker thread to keep the loop free."""
    with path.open("rb") as fh:
        while True:
            block = await asyncio.to_thread(fh.read, 64 * 1024)
            if not block:
                return
            yield block


async def _load(session: AsyncSession, doc_id: str) -> Document:
    from ..errors import NotFound

    doc = await session.get(Document, doc_id)
    if doc is None:
        raise NotFound("文档不存在", detail={"doc_id": doc_id})
    return doc

