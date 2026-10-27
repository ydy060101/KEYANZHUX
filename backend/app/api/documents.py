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
from ..models.orm import AssetRow, CitationRow, Document, ReferenceRow, SectionSummaryRow
from ..models.orm import Block as BlockRow
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
    """Counts for one document's card (the detail endpoint)."""
    return (await _stats_many(session, [doc_id]))[doc_id]


def _empty_stats() -> dict[str, int]:
    """The counters a card shows, all zero before any row is counted."""
    return {
        "blocks": 0,
        "figures": 0,
        "tables": 0,
        "formulas": 0,
        "references": 0,
        "citations": 0,
        "cited_references": 0,
        "uncited_references": 0,
        "dangling_citations": 0,
    }


async def _stats_many(session: AsyncSession, doc_ids: list[str]) -> dict[str, dict[str, int]]:
    """The library card's counts for a page of documents, in three queries.

    The list used to return an empty `stats` for every document, so the card's
    "N 块 · M 篇参考文献" never rendered. Asking per document would be an N+1
    over the page, so the counts are grouped by document instead.

    Figures, tables and formulas are counted from `assets`, not from block
    types: the parser types their captions as `caption` and keeps the graphic
    itself as an asset, so counting blocks would always report zero.
    """
    if not doc_ids:
        return {}
    out: dict[str, dict[str, int]] = {doc_id: _empty_stats() for doc_id in doc_ids}

    block_rows = await session.execute(
        select(BlockRow.doc_id, func.count()).where(BlockRow.doc_id.in_(doc_ids)).group_by(BlockRow.doc_id)
    )
    for doc_id, count in block_rows:
        out[doc_id]["blocks"] = count

    asset_rows = await session.execute(
        select(AssetRow.doc_id, AssetRow.kind, func.count())
        .where(AssetRow.doc_id.in_(doc_ids))
        .group_by(AssetRow.doc_id, AssetRow.kind)
    )
    for doc_id, kind, count in asset_rows:
        if kind in {"figure", "table", "formula"}:
            out[doc_id][f"{kind}s"] = count

    reference_rows = await session.execute(
        select(ReferenceRow.doc_id, ReferenceRow.id).where(ReferenceRow.doc_id.in_(doc_ids))
    )
    known: dict[str, set[str]] = {}
    for doc_id, ref_id in reference_rows:
        known.setdefault(doc_id, set()).add(ref_id.split(":", 1)[-1])
        out[doc_id]["references"] += 1

    citation_rows = await session.execute(
        select(CitationRow.doc_id, CitationRow.ref_ids).where(CitationRow.doc_id.in_(doc_ids))
    )
    cited: dict[str, set[str]] = {}
    for doc_id, ref_ids in citation_rows:
        out[doc_id]["citations"] += 1
        bucket = cited.setdefault(doc_id, set())
        for ref in ref_ids or []:
            bucket.add(ref.split(":", 1)[-1])

    for doc_id in doc_ids:
        used = cited.get(doc_id, set())
        names = known.get(doc_id, set())
        out[doc_id]["cited_references"] = len(used & names)
        out[doc_id]["uncited_references"] = len(names - used)
        out[doc_id]["dangling_citations"] = len(used - names)
    return out


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
    rows = list(
        await session.scalars(
            stmt.order_by(Document.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    )
    stats = await _stats_many(session, [doc.id for doc in rows])
    items = [_document_payload(doc, stats.get(doc.id)) for doc in rows]
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
    """Metadata, heading tree, asset index and references in one call (T2.6).

    The reader opens this before it renders a page, so it carries no block
    text: a 541-page book has 10 748 blocks, and shipping them all would make
    the first paint depend on a payload the reader does not need. Blocks are
    fetched per page (`/pages/{n}/blocks`) as the reader scrolls to them.

    Assets are listed by `kind` so the structure panel can show figures,
    tables and formulas without a second round trip; the image itself is still
    fetched per asset from `/assets/{asset_id}`.
    """
    doc = await _load(session, doc_id)
    # The outline is the section tracker's, not "every block typed heading":
    # the book has 1 014 heading-typed blocks but only 169 section starts, and
    # a tree of the former repeats one section id hundreds of times (T2.6).
    # `section_summaries` holds exactly the sections that started a section.
    sections = await session.scalars(
        select(SectionSummaryRow)
        .where(SectionSummaryRow.doc_id == doc_id)
        .order_by(SectionSummaryRow.page, SectionSummaryRow.section_id)
    )
    section_rows = list(sections)
    # The outline jumps to the heading block itself, not the first body block
    # after it, so the reader lands on the title it clicked. Ordered by reading
    # order and kept first-wins: a section id can name several blocks, and only
    # the heading that opened it is the jump target.
    heading_rows = await session.execute(
        select(BlockRow.section_id, BlockRow.id)
        .where(BlockRow.doc_id == doc_id, BlockRow.type == "heading")
        .order_by(BlockRow.page, BlockRow.reading_order)
    )
    heading_of: dict[str, str] = {}
    for section_id, block_id in heading_rows:
        if section_id and section_id not in heading_of:
            heading_of[section_id] = block_id
    outline = [
        {
            "id": section.section_id,
            "level": section.level or _section_level(section.title),
            "title": section.title[:200],
            "page": section.page,
            "block_id": heading_of.get(section.section_id, _first_block(section.block_ids)),
        }
        for section in section_rows
    ]
    references = list(
        await session.scalars(
            select(ReferenceRow).where(ReferenceRow.doc_id == doc_id).order_by(ReferenceRow.index)
        )
    )
    ref_pages = await _pages_of_blocks(session, doc_id, {row.block_id for row in references})
    assets = await session.scalars(
        select(AssetRow).where(AssetRow.doc_id == doc_id).order_by(AssetRow.page, AssetRow.id)
    )
    stored = doc.meta or {}
    return {
        "meta": {
            "title": doc.title,
            "authors": stored.get("authors", []),
            "abstract": stored.get("abstract"),
            "arxiv_id": doc.arxiv_id,
            "version": doc.version,
            "year": stored.get("year"),
            "venue": stored.get("venue"),
        },
        "outline": outline,
        "assets": [_asset_payload(row) for row in assets],
        "references": [_reference_payload(row, ref_pages.get(row.block_id)) for row in references],
    }


def _asset_payload(row: AssetRow) -> dict[str, Any]:
    return {
        "id": row.id.split(":", 1)[-1],
        "kind": row.kind,
        "page": row.page,
        "bbox": list(row.bbox or []),
        "path": f"/api/v1/documents/{row.doc_id}/assets/{row.id.split(':', 1)[-1]}",
        "html": row.html,
    }


def _section_level(title: str) -> int:
    """The heading's depth, from its numbering ("2.3.1" is level 3)."""
    match = re.match(r"^(\d+(?:\.\d+)*)", title.strip())
    if match is None:
        return 1
    return min(3, match.group(1).count(".") + 1)


def _first_block(block_ids: list[str] | None) -> str:
    """The block a section starts at, which is where the outline jumps to."""
    return block_ids[0] if block_ids else ""


def _heading_level(block: BlockRow) -> int:
    """Recover the outline level from the section title's numbering."""
    return _section_level(block.text)


def _reference_payload(row: ReferenceRow, page: int | None = None) -> dict[str, Any]:
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
        "page": page if page is not None else _page_of_block(row.block_id),
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
    citations = list(rows)
    pages = await _pages_of_blocks(session, doc_id, {row.block_id for row in citations})
    return [
        {
            "id": row.id.split(":", 1)[-1],
            "marker": row.marker,
            "ref_ids": [ref.split(":", 1)[-1] for ref in (row.ref_ids or [])],
            "block_id": row.block_id,
            "page": pages.get(row.block_id) or _page_of_block(row.block_id),
            "bbox": list(row.bbox or []),
            "method": row.method,
        }
        for row in citations
    ]


def _page_of_block(block_id: str) -> int | None:
    """The page a block id belongs to (`b12_3` → 12), or None.

    Only a fallback: the page is a column on the block row, and documents
    parsed before the page-scoped id scheme carry ids such as `b202` that
    would read as page 202 of a 75-page paper. `_pages_of_blocks` asks the
    database; this is for rows whose block is gone.
    """
    if not block_id.startswith("b"):
        return None
    head, _, rest = block_id[1:].partition("_")
    if not head.isdigit() or not rest:
        return None
    return int(head)


async def _pages_of_blocks(session: AsyncSession, doc_id: str, block_ids: set[str]) -> dict[str, int]:
    """The page each block sits on, as stored (T2.6).

    The reader draws a marker's hit box on the page the marker sits on, so a
    wrong page puts the box on a page it does not belong to — or, for a paper
    shorter than the id's number, nowhere at all.
    """
    if not block_ids:
        return {}
    rows = await session.execute(
        select(BlockRow.id, BlockRow.page).where(
            BlockRow.doc_id == doc_id, BlockRow.id.in_(block_ids)
        )
    )
    return {block_id: page for block_id, page in rows}


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

