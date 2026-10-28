"""Turn downloaded bytes into a library document (T5.1/T5.2).

Both the single-paper import and the reference batch need the same four steps:
hash the bytes, reuse a document with the same sha256 (H12), write the PDF and
create the row with the source metadata. Keeping that here means the two jobs
cannot drift in their deduplication behaviour.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..ingest import storage
from ..models.orm import Document
from .fetch import Resolved


async def store_download(
    session: AsyncSession,
    resolved: Resolved,
    data: bytes,
    *,
    source: str,
    ext_id: str,
    user: str,
) -> tuple[Document, bool, str]:
    """Return (document, reused, sha256); never writes the same bytes twice."""
    sha256 = storage.sha256_bytes(data)
    existing = await session.scalar(select(Document).where(Document.sha256 == sha256))
    if existing is not None:
        return existing, True, sha256

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
    return doc, False, sha256
