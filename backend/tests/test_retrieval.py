"""T3.2 acceptance: the hybrid pipeline and its recall on a small golden set.

The card asks for BM25 + 向量 + RRF + 重排 with a small-sample recall test, and
for every result to carry its chunk→block mapping. This module covers the
pipeline itself; `test_retrieval_scope.py` covers `scope` filtering.

**On the embedder.** The stub is a hashed bag-of-words: deterministic, and
lexical enough that the two retrievers can genuinely agree or disagree. The real
bge-m3 + bge-reranker numbers are measured by `tools/check_retrieval.py`, which
is the only place the 2 GB models are loaded (H15).
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from app.models.orm import Chunk
from app.rag.retrieve import Hit, Scope, _bm25, _rrf, retrieve
from retrieval_support import (
    GOLDEN,
    BagOfWordsEmbedder,
    MissingEmbedder,
    load_document,
)

DOC = "doc-transformer"


@pytest.fixture
async def corpus(session: Any, paper_chunks: list[Any]) -> dict[str, Any]:
    doc_id = await load_document(session, "Attention", DOC, paper_chunks)
    return {"session": session, "doc_id": doc_id, "chunks": paper_chunks}


# ---- the golden set ------------------------------------------------------


async def test_golden_set_recall(corpus: dict[str, Any]) -> None:
    """The card's acceptance: a small-sample recall measurement.

    Recall here is "the chunk holding the answer is among the 8 returned",
    which is what T3.3 needs: if the evidence is not in the top 8, no answer
    built from them can be correct, whatever the model does. The threshold is
    below 1.0 on purpose — one question in this set is answered by a chunk that
    also discusses layers and attention, so a lexical retriever can lose it to
    a nearer neighbour, and demanding perfection would be measuring the stub
    rather than the pipeline.
    """
    session = corpus["session"]
    embedder = BagOfWordsEmbedder()
    found: list[tuple[str, bool]] = []
    for question, needle in GOLDEN:
        result = await retrieve(session, question, Scope("doc", [corpus["doc_id"]]), embedder)
        hit = any(needle.lower() in item.text.lower() for item in result.hits)
        found.append((question, hit))
        if not hit:
            print(f"MISS: {question} (expected {needle!r})")

    recall = sum(1 for _, hit in found if hit) / len(found)
    print(f"recall@8 = {recall:.2f} over {len(found)} questions")
    assert recall >= 0.75, [question for question, hit in found if not hit]


async def test_every_hit_maps_back_to_blocks(corpus: dict[str, Any]) -> None:
    """H01: a hit that cannot name its blocks cannot produce an anchor."""
    session = corpus["session"]
    by_id = {f"{corpus['doc_id']}:{draft.block_ids[0]}": draft for draft in corpus["chunks"]}
    result = await retrieve(
        session, "multi-head attention", Scope("doc", [corpus["doc_id"]]), BagOfWordsEmbedder()
    )
    assert result.hits
    for hit in result.hits:
        assert hit.block_ids, hit.chunk_id
        assert hit.page_start >= 1 and hit.page_end >= hit.page_start, hit.chunk_id
        # The block ids are the ones the chunker assigned, not reconstructed.
        assert hit.block_ids == list(by_id[hit.chunk_id].block_ids)
        assert hit.text == by_id[hit.chunk_id].text


async def test_the_hit_text_is_the_chunk_text(corpus: dict[str, Any]) -> None:
    """The evidence handed to the answer layer is the stored chunk, verbatim.

    A retriever that trimmed or re-wrapped the passage would break H04's literal
    verification: the answer's numbers are checked against the text the
    citations point at, so that text must be exactly what is in the database.
    """
    session = corpus["session"]
    result = await retrieve(
        session, "warmup steps", Scope("doc", [corpus["doc_id"]]), BagOfWordsEmbedder()
    )
    stored = {
        row.id: row.text
        for row in await session.scalars(select(Chunk).where(Chunk.doc_id == corpus["doc_id"]))
    }
    for hit in result.hits:
        assert hit.text == stored[hit.chunk_id]


# ---- fusion --------------------------------------------------------------


async def test_bm25_terms_are_ored_not_anded(corpus: dict[str, Any]) -> None:
    """A question's words are OR-ed; the answering chunk need not contain all of them.

    The first implementation used `websearch_to_tsquery`, which ANDs. This test
    is the regression: "schedule" appears nowhere in the paper, so an AND-query
    over the three words returns nothing while the passage about `warmup_steps`
    is exactly what the question is after. On the real models an AND-query
    returned no candidates at all for 5 of the 8 golden questions, which made
    the "hybrid" retriever vector-only without saying so.
    """
    session = corpus["session"]
    texts = [hit for hit in await session.scalars(select(Chunk.text).where(Chunk.doc_id == corpus["doc_id"]))]
    assert not any("schedule" in text.lower() for text in texts)
    ids = await _bm25(session, "warmup steps schedule", [corpus["doc_id"]], 30)
    assert ids, "an OR-query should still find the chunks that mention warmup steps"


def test_fusion_rewards_agreement() -> None:
    """A chunk both retrievers rank highly beats one only one of them found."""
    lexical = ["a", "b", "c"]
    vector = ["b", "c", "d"]
    fused = dict(_rrf(lexical, vector, 60))
    # `b` is 2nd in both; `a` is 1st in one list and absent from the other.
    assert fused["b"] > fused["a"]
    assert fused["c"] > fused["a"]
    assert fused["a"] > fused["d"]
    assert [chunk_id for chunk_id, _ in _rrf(lexical, vector, 60)] == ["b", "c", "a", "d"]


def test_fusion_of_one_list_keeps_its_order() -> None:
    """H08: with no vectors, the lexical order must survive unchanged."""
    fused = [chunk_id for chunk_id, _ in _rrf(["x", "y", "z"], [], 60)]
    assert fused == ["x", "y", "z"]


def test_fusion_is_deterministic_on_ties() -> None:
    """H06: equal scores break on the id, not on dict insertion order."""
    assert _rrf(["b"], ["a"], 60) == [("a", 1 / 61), ("b", 1 / 61)]


# ---- rerank and degradation ---------------------------------------------


async def test_the_reranker_replaces_the_fused_order(corpus: dict[str, Any]) -> None:
    """The cross-encoder decides the final order, and its score is the hit's score.

    This is what H03 needs: `QA_MIN_SCORE` is compared against the reranker's
    absolute score, so a pipeline that kept the RRF value would make the
    threshold meaningless.
    """

    class Scorer(BagOfWordsEmbedder):
        """Scores by position: the last candidate is judged best."""

        async def rerank(self, query: str, documents: list[str]) -> list[float] | None:
            return [float(index) for index in range(len(documents))]

    session = corpus["session"]
    result = await retrieve(session, "attention", Scope("doc", [corpus["doc_id"]]), Scorer())
    assert result.stages["reranked"] is True
    scores = [hit.score for hit in result.hits]
    assert scores == sorted(scores, reverse=True)
    assert result.hits[0].score == max(scores)


async def test_a_missing_reranker_leaves_the_fused_order(corpus: dict[str, Any]) -> None:
    """H08: degradation is reported, not hidden."""
    session = corpus["session"]
    result = await retrieve(
        session, "attention", Scope("doc", [corpus["doc_id"]]), BagOfWordsEmbedder()
    )
    assert result.stages["reranked"] is False
    rrf_scores = [hit.rrf for hit in result.hits]
    assert rrf_scores == sorted(rrf_scores, reverse=True)


async def test_a_missing_embedder_falls_back_to_bm25(corpus: dict[str, Any]) -> None:
    """H08: no vectors means BM25 only, and the result says so."""
    session = corpus["session"]
    result = await retrieve(
        session, "multi-head attention", Scope("doc", [corpus["doc_id"]]), MissingEmbedder()
    )
    assert result.stages["vector"] == 0
    assert result.stages["vector_available"] is False
    assert result.hits, "BM25 found nothing; the fallback is not working"
    assert all(hit.vector_rank is None for hit in result.hits)


async def test_ranks_record_which_stage_found_each_hit(corpus: dict[str, Any]) -> None:
    """A hit's provenance is visible: found by both stages, or by one."""
    session = corpus["session"]
    result = await retrieve(
        session, "multi-head attention", Scope("doc", [corpus["doc_id"]]), BagOfWordsEmbedder()
    )
    assert any(hit.bm25_rank is not None and hit.vector_rank is not None for hit in result.hits)
    for hit in result.hits:
        if hit.bm25_rank is not None:
            assert hit.bm25_rank >= 1


async def test_the_limit_caps_the_returned_hits(corpus: dict[str, Any]) -> None:
    session = corpus["session"]
    result = await retrieve(
        session, "attention", Scope("doc", [corpus["doc_id"]]), BagOfWordsEmbedder(), limit=3
    )
    assert len(result.hits) == 3
    assert result.stages["returned"] == 3


async def test_an_empty_library_returns_no_hits(session: Any) -> None:
    result = await retrieve(session, "attention", Scope("all", []), BagOfWordsEmbedder())
    assert result.hits == []
    assert result.top_score == 0.0


def test_hit_serialises_its_anchor_fields() -> None:
    """The shape T3.3 consumes: a hit carries everything an Anchor needs."""
    hit = Hit(
        chunk_id="doc:b1_1",
        doc_id="doc",
        text="text",
        block_ids=["b1_1"],
        section_id="h1",
        page_start=1,
        page_end=2,
        score=0.5,
    )
    payload = hit.as_dict()
    for key in ("chunk_id", "doc_id", "block_ids", "page_start", "page_end", "score"):
        assert key in payload
    assert payload["block_ids"] == ["b1_1"]
