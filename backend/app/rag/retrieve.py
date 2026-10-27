"""Hybrid retrieval: BM25 + vectors → RRF → rerank (T3.2, 01 §9).

The pipeline is the one 01 §9 names, in the order it names it:

  1. **BM25 over `chunks.tsv`** — PostgreSQL's full-text search with `ts_rank_cd`,
     taking the top `retrieval_bm25_k` (30). Lexical matching is what catches a
     question that quotes a term the document uses verbatim ("BLEU", "Adam"),
     which a dense vector smooths away.
  2. **Cosine over `chunks.embedding`** — pgvector's HNSW index, taking the top
     `retrieval_vector_k` (30). This is what catches a question phrased in words
     the document never uses.
  3. **Reciprocal Rank Fusion** — the two ranked lists are merged by
     `1 / (k + rank)`. RRF needs no score calibration between a `ts_rank_cd`
     value and a cosine similarity, which is why 01 §9 specifies it: the two
     numbers are not on a common scale, and any weighted sum would be arbitrary.
  4. **Cross-encoder rerank** — bge-reranker scores each candidate against the
     question, and the top `retrieval_rerank_k` (8) survive. This is the step
     that decides relevance for a real question, and its top score is what
     H03's `QA_MIN_SCORE` threshold is compared against.

Every result carries the chunk's `block_ids[]` and its page range, so a caller
can turn it into an anchor (H01) without another query. That is the card's hard
requirement: "检索结果必须带 chunk→block 映射".

**Degradation (H08).** If the model is unavailable the vector list is empty and
RRF falls back to BM25's order; if the reranker is unavailable the fused order
stands. Both are reported in `stages`, so a caller can tell a degraded ranking
from a full one instead of assuming every stage ran.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import String, bindparam, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models.orm import Chunk
from .embedding import Embedder


@dataclass
class Scope:
    """What a query may search (01 §5.2's `scope`).

    `doc` restricts to the documents named, `set` to a list of them, and `all`
    to the whole library. A `doc`/`set` scope with no document ids matches
    nothing rather than everything: a client that meant "all" says `all`, and a
    request that arrived with an empty list is a bug on its side that must not
    quietly turn into a library-wide search.
    """

    type: str = "doc"
    doc_ids: list[str] = field(default_factory=list)

    def doc_filter(self) -> list[str] | None:
        """The document ids to constrain to, or None for the whole library."""
        if self.type == "all":
            return None
        return list(self.doc_ids)

    def describe(self) -> dict[str, Any]:
        return {"type": self.type, "doc_ids": list(self.doc_ids)}


@dataclass
class Hit:
    """One retrieved chunk, with everything needed to anchor it."""

    chunk_id: str
    doc_id: str
    text: str
    block_ids: list[str]
    section_id: str | None
    page_start: int
    page_end: int
    score: float
    # Where this chunk ranked in each retriever, 1-based, None when that stage
    # did not return it. Kept for the provenance panel and for debugging a
    # surprising order: "found by both, 3rd and 11th" is a different signal
    # from "found by the reranker alone".
    bm25_rank: int | None = None
    vector_rank: int | None = None
    rrf: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "text": self.text,
            "block_ids": list(self.block_ids),
            "section_id": self.section_id,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "score": self.score,
            "bm25_rank": self.bm25_rank,
            "vector_rank": self.vector_rank,
            "rrf": self.rrf,
        }


@dataclass
class RetrievalResult:
    """The ranked hits and which stages actually ran."""

    hits: list[Hit]
    query: str
    scope: dict[str, Any]
    stages: dict[str, Any]

    @property
    def top_score(self) -> float:
        """The best score, which is what H03's refusal threshold compares to."""
        return self.hits[0].score if self.hits else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "scope": self.scope,
            "stages": self.stages,
            "hits": [hit.as_dict() for hit in self.hits],
        }


async def retrieve(
    session: AsyncSession,
    query: str,
    scope: Scope,
    embedder: Embedder,
    *,
    limit: int | None = None,
) -> RetrievalResult:
    """Run the full pipeline for one question."""
    settings = get_settings()
    wanted = limit or settings.retrieval_rerank_k
    doc_ids = scope.doc_filter()
    stages: dict[str, Any] = {}

    lexical = await _bm25(session, query, doc_ids, settings.retrieval_bm25_k)
    stages["bm25"] = len(lexical)

    vector = await _vector(session, query, doc_ids, embedder, settings.retrieval_vector_k)
    stages["vector"] = len(vector)
    stages["vector_available"] = embedder.available or bool(vector)

    fused = _rrf(lexical, vector, settings.rrf_k)
    stages["fused"] = len(fused)

    ranked = _to_hits(await _hydrate(session, [chunk_id for chunk_id, _ in fused]), fused, lexical, vector)
    reranked = await _rerank(query, ranked, embedder)
    stages["reranked"] = reranked is not None
    if reranked is not None:
        ranked = reranked

    stages["returned"] = min(len(ranked), wanted)
    return RetrievalResult(hits=ranked[:wanted], query=query, scope=scope.describe(), stages=stages)


# ---- stage 1: BM25 -------------------------------------------------------


async def _bm25(
    session: AsyncSession, query: str, doc_ids: list[str] | None, k: int
) -> list[str]:
    """Chunk ids by full-text rank, best first.

    **The terms are OR-ed, not AND-ed.** `websearch_to_tsquery` — the obvious
    choice, since it never raises on punctuation — requires *every* word of the
    question to appear in one chunk. On the fixtures that returned nothing for
    5 of 8 golden questions: "How many warmup steps does the learning rate
    schedule use?" demands "schedule" as well as "warmup", and the chunk that
    answers it says "we increased the learning rate linearly for the first
    warmup_steps training steps". A lexical retriever for questions must rank
    by how many terms match and how close they are, which is exactly what
    `ts_rank_cd` does over an OR-query; requiring all of them turns the hybrid
    into a vector-only search (the R1 run showed `bm25: 0` five times over).

    `ts_rank_cd` rather than `ts_rank`: cover density rewards a chunk where the
    query's terms appear close together, which is what "the passage about X"
    means.

    The query is rebuilt from `[A-Za-z0-9]+` runs rather than passed through:
    `to_tsquery` has its own syntax (`&`, `|`, `!`, `:`, parentheses) and a
    question containing any of them would either change the query's meaning or
    raise. Stop words are left in — the `english` configuration drops them, and
    a chunk that matches only a stop word ranks last anyway.
    """
    words = re.findall(r"[A-Za-z0-9]+", query)
    if not words:
        return []
    if doc_ids is not None and not doc_ids:
        return []
    where = "tsv @@ to_tsquery('english', :tsq)"
    params: dict[str, Any] = {"tsq": " | ".join(words), "k": k}
    scoped = doc_ids is not None
    if scoped:
        where += " AND doc_id = ANY(:doc_ids)"
        params["doc_ids"] = doc_ids
    statement = text(
        f"""
        SELECT id
        FROM chunks
        WHERE {where}
        ORDER BY ts_rank_cd(tsv, to_tsquery('english', :tsq)) DESC
        LIMIT :k
        """
    )
    if scoped:
        statement = statement.bindparams(bindparam("doc_ids", type_=ARRAY(String)))
    rows = await session.execute(statement, params)
    return [row[0] for row in rows]


# ---- stage 2: vectors ----------------------------------------------------


async def _vector(
    session: AsyncSession, query: str, doc_ids: list[str] | None, embedder: Embedder, k: int
) -> list[str]:
    """Chunk ids by cosine distance, best first; empty when the model is away."""
    if doc_ids is not None and not doc_ids:
        return []
    vector = await embedder.embed_one(query)
    if vector is None:
        return []
    stmt = select(Chunk.id).where(Chunk.embedding.is_not(None))
    if doc_ids is not None:
        stmt = stmt.where(Chunk.doc_id.in_(doc_ids))
    stmt = stmt.order_by(Chunk.embedding.cosine_distance(vector)).limit(k)
    return list(await session.scalars(stmt))


# ---- stage 3: fusion -----------------------------------------------------


def _rrf(lexical: list[str], vector: list[str], k: int) -> list[tuple[str, float]]:
    """Reciprocal rank fusion of two ranked id lists (01 §9).

    A chunk found by both stages rises above one found by either alone, which
    is the point: the two stages fail in different ways, so agreement between
    them is evidence. `k` (60 by default) damps the top ranks so a single
    confident first place does not dominate the fused order.

    Ties break on the chunk id, so the order is reproducible for a given input
    (H06) rather than dependent on dict insertion order.
    """
    scores: dict[str, float] = {}
    for ranked in (lexical, vector):
        for rank, chunk_id in enumerate(ranked, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def _to_hits(
    candidates: dict[str, Chunk],
    fused: list[tuple[str, float]],
    lexical: list[str],
    vector: list[str],
) -> list[Hit]:
    """Turn fused ids into hits, in fused order, with each stage's rank."""
    lexical_rank = {chunk_id: rank for rank, chunk_id in enumerate(lexical, start=1)}
    vector_rank = {chunk_id: rank for rank, chunk_id in enumerate(vector, start=1)}
    hits: list[Hit] = []
    for chunk_id, rrf in fused:
        chunk = candidates.get(chunk_id)
        if chunk is None:
            # Deleted between the search and the fetch: skipping it is correct,
            # and the hit count in `stages` still says how many were fused.
            continue
        hits.append(
            Hit(
                chunk_id=chunk.id,
                doc_id=chunk.doc_id,
                text=chunk.text,
                block_ids=list(chunk.block_ids or []),
                section_id=chunk.section_id,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                score=rrf,
                rrf=rrf,
                bm25_rank=lexical_rank.get(chunk_id),
                vector_rank=vector_rank.get(chunk_id),
            )
        )
    return hits


async def _hydrate(session: AsyncSession, chunk_ids: list[str]) -> dict[str, Chunk]:
    """Fetch the fused chunks in one query."""
    if not chunk_ids:
        return {}
    rows = await session.scalars(select(Chunk).where(Chunk.id.in_(chunk_ids)))
    return {row.id: row for row in rows}


# ---- stage 4: rerank -----------------------------------------------------


async def _rerank(query: str, hits: list[Hit], embedder: Embedder) -> list[Hit] | None:
    """Cross-encoder scores, or None when the reranker is unavailable.

    The reranker replaces the fused order rather than adjusting it: a
    cross-encoder reads the question and the passage together, which is a
    stronger signal than either retriever, and 01 §9 says its output is what
    the answer is built from. Its absolute score is also what H03's threshold
    is calibrated against, so mixing it with the RRF value would leave the
    threshold meaning nothing.

    Ties keep the fused order (`sorted` is stable), so a reranker that returns
    equal scores degrades to the fusion rather than to an arbitrary order.
    """
    if not hits:
        return None
    scores = await embedder.rerank(query, [hit.text for hit in hits])
    if scores is None or len(scores) != len(hits):
        return None
    for hit, score in zip(hits, scores, strict=True):
        hit.score = score
    return sorted(hits, key=lambda hit: -hit.score)
