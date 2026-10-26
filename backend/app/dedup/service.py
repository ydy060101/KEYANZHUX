"""Three-level semantic dedup (01 §8, T1.4).

L1 exact (sha256) → L2 version (same arXiv id, different version) →
L3 content (title+abstract cosine and MinHash Jaccard over the opening blocks).

L3 needs embeddings. When the model is unavailable only L1/L2 run and the
caller is told the level that could not be checked, rather than being told
"no duplicate" when the check never happened (H02).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models.orm import DocFingerprint, Document
from ..models.schemas import DedupInfo
from ..rag.embedding import Embedder, cosine
from . import fingerprint

logger = logging.getLogger(__name__)

_VERSION_RE = re.compile(r"v(\d+)$")


@dataclass
class Candidate:
    """What a document looks like to the dedup rules, before it is stored."""

    sha256: str
    arxiv_id: str | None
    version: str | None
    title: str
    abstract: str
    body: str


def parse_version(value: str | None) -> int | None:
    if not value:
        return None
    match = _VERSION_RE.search(value.strip())
    return int(match.group(1)) if match else None


def _newer(new_version: str | None, existing_version: str | None) -> bool:
    new_no = parse_version(new_version)
    old_no = parse_version(existing_version)
    if new_no is None or old_no is None:
        return False
    return new_no > old_no


def _version_reason(
    new_version: str | None, existing_version: str | None
) -> tuple[Literal["keep_existing", "replace", "ask"], str]:
    """Return (suggestion, reason) for two versions of one paper.

    01 §8: when both versions parse, keep the newer one. `keep_existing` keeps
    the library copy, so a newer upload is suggested as `replace`.
    """
    if _newer(new_version, existing_version):
        return (
            "replace",
            f"库中已有 {existing_version}，新上传的 {new_version} 版本较新，建议用新版本替换",
        )
    if _newer(existing_version, new_version):
        return (
            "keep_existing",
            f"库中已有版本较新（{existing_version}），新上传的是 {new_version}，建议保留现有版本",
        )
    return "ask", "版本号无法比较，请手动选择保留哪一个"


def _signature_text(title: str, abstract: str, body: str) -> str:
    return "\n".join(part for part in (title, abstract, body) if part)


async def check(
    session: AsyncSession,
    candidate: Candidate,
    *,
    exclude_doc_id: str | None = None,
    embedder: Embedder | None = None,
    load_model: bool = True,
) -> DedupInfo | None:
    """Return the first duplicate hit, or None when the document is new.

    `load_model=False` keeps the upload path fast: L1/L2 always run, and L3
    runs on MinHash alone when the embedding model is not already loaded.
    """
    settings = get_settings()

    # L1 — identical bytes.
    stmt = select(Document).where(Document.sha256 == candidate.sha256)
    if exclude_doc_id:
        stmt = stmt.where(Document.id != exclude_doc_id)
    exact = await session.scalar(stmt)
    if exact is not None:
        return DedupInfo(
            level="exact_duplicate",
            matched_doc_id=exact.id,
            similarity=1.0,
            existing_version=exact.version,
            new_version=candidate.version,
            suggestion="keep_existing",
            reason="文件内容完全相同（sha256 一致）",
        )

    # L2 — same arXiv id, different version.
    if candidate.arxiv_id:
        siblings_stmt = select(Document).where(Document.arxiv_id == candidate.arxiv_id)
        if exclude_doc_id:
            siblings_stmt = siblings_stmt.where(Document.id != exclude_doc_id)
        siblings = await session.scalars(siblings_stmt)
        for sibling in siblings:
            if sibling.version == candidate.version:
                continue
            suggestion, reason = _version_reason(candidate.version, sibling.version)
            return DedupInfo(
                level="same_paper_other_version",
                matched_doc_id=sibling.id,
                similarity=1.0,
                existing_version=sibling.version,
                new_version=candidate.version,
                suggestion=suggestion,
                reason=reason,
            )

    # L3 — content similarity.
    return await _content_duplicate(
        session, candidate, settings, embedder, exclude_doc_id, load_model=load_model
    )


async def _content_duplicate(
    session: AsyncSession,
    candidate: Candidate,
    settings: Any,
    embedder: Embedder | None,
    exclude_doc_id: str | None,
    *,
    load_model: bool = True,
) -> DedupInfo | None:
    pairs_stmt = select(Document, DocFingerprint).join(
        DocFingerprint, DocFingerprint.doc_id == Document.id
    )
    if exclude_doc_id:
        pairs_stmt = pairs_stmt.where(Document.id != exclude_doc_id)
    rows = await session.execute(pairs_stmt)
    pairs: list[tuple[Document, DocFingerprint]] = [(row[0], row[1]) for row in rows.all()]
    if not pairs:
        return None

    new_sig = fingerprint.signature(_signature_text(candidate.title, candidate.abstract, candidate.body))
    new_vec = None
    embedder = embedder or _default_embedder()
    if embedder is not None:
        vectors = await embedder.embed([_title_abstract(candidate.title, candidate.abstract)], load=load_model)
        if vectors is not None and len(vectors):
            new_vec = vectors[0]
    if new_vec is None:
        logger.info("L3 vector check skipped: embedding model unavailable")

    best: tuple[float, Document, DocFingerprint] | None = None
    for doc, fp in pairs:
        existing_sig = list(fp.minhash or [])
        jac = fingerprint.jaccard(new_sig, existing_sig)
        cos = 1.0
        if new_vec is not None and fp.title_abs_embedding is not None:
            cos = cosine(new_vec, list(fp.title_abs_embedding))
        score = min(cos, jac) if new_vec is not None else jac
        if best is None or score > best[0]:
            best = (score, doc, fp)

    if best is None:
        return None
    score, doc, fp = best
    jac = fingerprint.jaccard(new_sig, list(fp.minhash or []))
    cos = 1.0
    if new_vec is not None and fp.title_abs_embedding is not None:
        cos = cosine(new_vec, list(fp.title_abs_embedding))

    if cos >= settings.dedup_l3_cosine and jac >= settings.dedup_l3_minhash_jaccard:
        level = "content_duplicate"
        suggestion = "ask"
        reason = (
            f"标题与摘要高度相似（余弦 {cos:.2f}），正文开头重合度 {jac:.0%}；"
            "内容相同但可能是不同格式，请选择保留哪一个或两者都保留"
        )
    elif cos >= settings.dedup_l3_cosine_possible:
        level = "possible_duplicate"
        suggestion = "ask"
        reason = f"标题与摘要相似（余弦 {cos:.2f}），请确认是否为同一篇论文"
    else:
        return None

    return DedupInfo(
        level=level,
        matched_doc_id=doc.id,
        similarity=round(cos, 4),
        existing_version=doc.version,
        new_version=candidate.version,
        suggestion=suggestion,
        reason=reason,
    )


def _title_abstract(title: str, abstract: str) -> str:
    return f"{title}\n{abstract}".strip()


def _default_embedder() -> Embedder | None:
    from ..rag.embedding import get_embedder

    return get_embedder()


async def store_fingerprint(
    session: AsyncSession,
    doc_id: str,
    candidate: Candidate,
    *,
    embedder: Embedder | None = None,
) -> DocFingerprint:
    """Persist the fingerprint L3 compares against on the next upload."""
    text = _signature_text(candidate.title, candidate.abstract, candidate.body)
    sig = fingerprint.signature(text)

    vector = None
    embedder = embedder or _default_embedder()
    if embedder is not None:
        # `load=False`: a first model load can take minutes, and the parse job
        # must not wait on it. The vector is filled in by the embedding backfill
        # and L3 falls back to MinHash until then (H08).
        vectors = await embedder.embed(
            [_title_abstract(candidate.title, candidate.abstract)], load=False
        )
        if vectors is not None and len(vectors):
            vector = [float(x) for x in vectors[0]]

    fp = await session.get(DocFingerprint, doc_id)
    if fp is None:
        fp = DocFingerprint(doc_id=doc_id)
        session.add(fp)
    fp.minhash = sig
    fp.title_abs_embedding = vector
    fp.first_pages_text_hash = fingerprint.hash_token(text[:4000]).to_bytes(8, "big").hex()
    await session.flush()
    return fp
