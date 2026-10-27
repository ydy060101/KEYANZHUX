"""Document CRUD, upload and PDF streaming (01 §5.1, T1.2)."""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, Header, Query, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import SessionDep, UserIdDep
from ..errors import NotFound
from ..ingest import storage
from ..ingest.validate import validate_upload
from ..models.orm import AssetRow, CitationRow, Document, ReferenceRow
from ..models.orm import Block as BlockRow
from ..models.schemas import BlockType
from ..workers import queue

logger = logging.getLogger(__name__)

router = APIRouter(tags=["documents"])

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


@dataclass
class QuickSignals:
    """What the upload path can learn about a PDF without parsing it."""

    arxiv_id: str | None
    version: str | None
    title: str
    body: str


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
    """Counts for the library card.

    Figures, tables and formulas are counted from `assets`, not from block
    types: the parser types their captions as `caption` and keeps the graphic
    itself as an asset, so counting blocks would always report zero.
    """
    rows = await session.execute(
        select(BlockRow.type, func.count()).where(BlockRow.doc_id == doc_id).group_by(BlockRow.type)
    )
    counts: dict[BlockType, int] = {row[0]: row[1] for row in rows}
    assets = await session.execute(
        select(AssetRow.kind, func.count()).where(AssetRow.doc_id == doc_id).group_by(AssetRow.kind)
    )
    asset_counts = {kind: count for kind, count in assets}
    references = await session.scalar(
        select(func.count()).select_from(ReferenceRow).where(ReferenceRow.doc_id == doc_id)
    )
    citations = await _citation_coverage(session, doc_id)
    return {
        "blocks": sum(counts.values()),
        "figures": asset_counts.get("figure", 0),
        "tables": asset_counts.get("table", 0),
        "formulas": asset_counts.get("formula", 0),
        "references": references or 0,
        **citations,
    }


async def _citation_coverage(session: AsyncSession, doc_id: str) -> dict[str, int]:
    """How much of the bibliography the body cites (T2.3).

    Derived from the stored rows rather than a counter column: the numbers
    then cannot drift from the citations they describe, and re-parsing a
    document updates them for free.
    """
    rows = await session.scalars(select(CitationRow.ref_ids).where(CitationRow.doc_id == doc_id))
    cited: set[str] = set()
    dangling: set[str] = set()
    for ref_ids in rows:
        for ref in ref_ids or []:
            cited.add(ref.split(":", 1)[-1])
    known = set(
        await session.scalars(select(ReferenceRow.id).where(ReferenceRow.doc_id == doc_id))
    )
    known_ids = {ref.split(":", 1)[-1] for ref in known}
    dangling = cited - known_ids
    return {
        "citations": await session.scalar(
            select(func.count()).select_from(CitationRow).where(CitationRow.doc_id == doc_id)
        )
        or 0,
        "cited_references": len(cited & known_ids),
        "uncited_references": len(known_ids - cited),
        "dangling_citations": len(dangling),
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
            # Re-uploading also repairs a row whose file went missing, which is
            # the only way the user can recover from a moved data directory.
            repaired = storage.ensure_pdf(existing.file_path, data)
            if str(repaired) != existing.file_path:
                existing.file_path = str(repaired)
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
        signals = _quick_signals(filename, data)
        dedup = await _detect_duplicate(session, signals, sha256)
        doc = Document(
            sha256=sha256,
            title=signals.title or Path(filename).stem,
            arxiv_id=signals.arxiv_id,
            version=signals.version,
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
                "dedup": dedup.model_dump() if dedup else None,
            }
        )

    await session.commit()
    for item in results:
        if not await queue.enqueue(item["job_id"]):
            import asyncio

            asyncio.create_task(queue.run_in_background(item["job_id"]))
    return results


@router.post("/documents/{doc_id}/dedup/resolve")
async def resolve_dedup(doc_id: str, body: dict[str, Any], session: SessionDep) -> dict[str, Any]:
    """Act on a duplicate warning (01 §8).

    `keep_existing` discards the new upload, `replace` discards the library copy
    in favour of the new one, and `keep_both` keeps both — which 01 §8 requires
    to stay possible when the same content arrived in a different format.
    """
    action = body.get("action")
    target_id = body.get("target_id")
    if action not in {"keep_existing", "replace", "keep_both"}:
        from ..errors import InvalidRequest

        raise InvalidRequest("action 必须是 keep_existing / replace / keep_both", detail={"action": action})

    doc = await _load(session, doc_id)

    if action == "keep_both":
        return _document_payload(doc)

    if not target_id:
        from ..errors import InvalidRequest

        raise InvalidRequest("该操作需要 target_id", detail={"action": action})

    other = await _load(session, str(target_id))
    if action == "keep_existing":
        # The new document goes away; the library copy stays untouched.
        file_path = doc.file_path
        await session.delete(doc)
        await session.commit()
        storage.remove_document(doc_id, file_path)
        return _document_payload(other)

    # replace: the new document survives, the old one and its files go.
    file_path = other.file_path
    await session.delete(other)
    await session.commit()
    storage.remove_document(other.id, file_path)
    return _document_payload(doc)


@router.get("/documents/{doc_id}/versions/diff")
async def version_diff(
    doc_id: str,
    session: SessionDep,
    other: Annotated[str, Query(description="The version to compare against")],
) -> dict[str, Any]:
    """Section-level diff plus a <=200 character summary (T1.5).

    The summary is generated from the statistics, never from the raw text, and
    any digit it states must already appear in them (H04).
    """
    from ..ingest import diff as diff_mod
    from ..llm.gateway import get_gateway

    await _load(session, doc_id)
    await _load(session, other)

    # A version with no parsed sections cannot be compared: every section of the
    # other side would look removed, and "no changes" would be equally false.
    # Report that plainly instead of inventing a diff (CR-003).
    parsed = {
        key: bool(await session.scalar(select(BlockRow.id).where(BlockRow.doc_id == key).limit(1)))
        for key in (doc_id, other)
    }
    if not all(parsed.values()):
        return {
            "other_id": other,
            "stats": {},
            "sections": [],
            "summary": "两版本文档尚未解析完成，暂时无法比较章节变化；解析完成后再查看。",
            "comparable": False,
        }

    stats, _raw, changes = await diff_mod.compare(session, doc_id, other)
    summary = await diff_mod.summarise(stats, changes, get_gateway())
    return {
        "other_id": other,
        "stats": stats,
        "sections": changes,
        "summary": summary,
        "comparable": True,
    }


@router.get("/documents/{doc_id}/pages/{page_no}/blocks")
async def page_blocks(doc_id: str, page_no: int, session: SessionDep) -> list[dict[str, Any]]:
    """Every block on one page, in reading order (T2.2, T2.6)."""
    await _load(session, doc_id)
    rows = await session.scalars(
        select(BlockRow)
        .where(BlockRow.doc_id == doc_id, BlockRow.page == page_no)
        .order_by(BlockRow.reading_order)
    )
    return [_block_payload(row) for row in rows]


def _block_payload(row: BlockRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "type": row.type,
        "page": row.page,
        "bbox": list(row.bbox or []),
        "reading_order": row.reading_order,
        "section_id": row.section_id,
        "text": row.text,
        "latex": row.latex,
        "html": row.html,
        "asset_id": row.asset_id,
        "lang": row.lang,
        "confidence": row.confidence,
    }


@router.get("/documents/{doc_id}/assets/{asset_id}")
async def get_asset(doc_id: str, asset_id: str, session: SessionDep) -> Response:
    """The cropped figure, table or formula image (T2.2).

    The crop is the fallback the reader shows when extracted structure is
    uncertain, so it must always be served from the stored bytes.
    """
    await _load(session, doc_id)
    asset = await session.get(AssetRow, f"{doc_id}:{asset_id}")
    if asset is None:
        raise NotFound("资源不存在", detail={"asset_id": asset_id})
    path = Path(asset.path)
    data = await asyncio.to_thread(path.read_bytes)
    return Response(content=data, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/documents/{doc_id}/structure")
async def get_structure(doc_id: str, session: SessionDep) -> dict[str, Any]:
    """Metadata, heading tree and references in one call (T2.1, T2.6)."""
    doc = await _load(session, doc_id)
    blocks = await session.scalars(
        select(BlockRow).where(BlockRow.doc_id == doc_id).order_by(BlockRow.reading_order)
    )
    outline = [
        {
            "id": block.section_id,
            "level": _heading_level(block),
            "title": block.text.strip()[:200],
            "page": block.page,
            "block_id": block.id,
        }
        for block in blocks
        if block.type == "heading"
    ]
    references = await session.scalars(
        select(ReferenceRow).where(ReferenceRow.doc_id == doc_id).order_by(ReferenceRow.index)
    )
    return {
        "meta": {
            "title": doc.title,
            "authors": [],
            "abstract": None,
            "arxiv_id": doc.arxiv_id,
            "version": doc.version,
            "year": None,
        },
        "outline": outline,
        "references": [_reference_payload(row) for row in references],
    }


def _heading_level(block: BlockRow) -> int:
    """Recover the outline level from the section title's numbering."""
    match = re.match(r"^(\d+(?:\.\d+)*)", block.text.strip())
    if match is None:
        return 1
    return min(3, match.group(1).count(".") + 1)


def _reference_payload(row: ReferenceRow) -> dict[str, Any]:
    return {
        "id": row.id.split(":", 1)[-1],
        "index": row.index,
        "raw": row.raw,
        "title": row.title,
        "authors": list(row.authors or []),
        "year": row.year,
        "doi": row.doi,
        "arxiv_id": row.arxiv_id,
        "block_id": row.block_id,
        "bbox": list(row.bbox or []),
    }


@router.get("/documents/{doc_id}/citations")
async def get_citations(doc_id: str, session: SessionDep) -> list[dict[str, Any]]:
    """In-text markers mapped to reference ids, each with its anchor (T2.3).

    Coverage travels in the document's `stats` instead of here, so the shape
    stays the array the contract specifies.
    """
    await _load(session, doc_id)
    rows = await session.scalars(
        select(CitationRow).where(CitationRow.doc_id == doc_id).order_by(CitationRow.id)
    )
    return [
        {
            "id": row.id.split(":", 1)[-1],
            "marker": row.marker,
            "ref_ids": [ref.split(":", 1)[-1] for ref in (row.ref_ids or [])],
            "block_id": row.block_id,
            "bbox": list(row.bbox or []),
            "method": row.method,
        }
        for row in rows
    ]


@router.get("/documents/{doc_id}/references")
async def get_references(doc_id: str, session: SessionDep) -> list[dict[str, Any]]:
    await _load(session, doc_id)
    rows = await session.scalars(
        select(ReferenceRow).where(ReferenceRow.doc_id == doc_id).order_by(ReferenceRow.index)
    )
    return [_reference_payload(row) for row in rows]


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
    path = storage.resolve(doc.file_path)
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


def _quick_signals(filename: str, data: bytes) -> QuickSignals:
    """arXiv id, version, title and opening text — read without a full parse.

    The upload response must be fast, so dedup uses the filename for the id and
    the first page's text for content. The parse job recomputes both properly.
    """
    from ..ingest.parser import ARXIV_RE, reading_order
    from ..ingest.pdfio import close_document, open_document_bytes, page

    arxiv_id: str | None = None
    version: str | None = None
    match = ARXIV_RE.search(filename)
    if match:
        arxiv_id, version = match.group(1), match.group(2)

    title = Path(filename).stem
    body = ""
    try:
        doc = open_document_bytes(data)
        try:
            first = page(doc, 0)
            blocks = reading_order(first)
            texts = [block.text.strip() for block in blocks if block.text.strip()]
            if texts:
                title = texts[0][:300]
                body = "\n".join(texts[:12])
            if arxiv_id is None:
                # The arXiv stamp sits anywhere on page 1 (often in the margin),
                # so search all of it rather than the leading blocks.
                found = ARXIV_RE.search(" ".join(texts))
                if found:
                    arxiv_id, version = found.group(1), found.group(2)
        finally:
            close_document(doc)
    except Exception:
        # A PDF PyMuPDF cannot open yet is still accepted; the parse job will
        # report the real failure. Dedup falls back to L1 on sha256 alone.
        logger.warning("quick dedup signals unavailable for %s", filename)
    return QuickSignals(arxiv_id=arxiv_id, version=version, title=title, body=body)


async def _detect_duplicate(session: AsyncSession, signals: QuickSignals, sha256: str) -> Any:
    from ..dedup.service import Candidate, check

    candidate = Candidate(
        sha256=sha256,
        arxiv_id=signals.arxiv_id,
        version=signals.version,
        title=signals.title,
        abstract="",
        body=signals.body,
    )
    return await check(session, candidate, load_model=False)

