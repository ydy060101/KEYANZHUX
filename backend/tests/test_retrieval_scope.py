"""T3.2 acceptance: `scope` filtering (01 §5.2).

A scope is the boundary of what a question may be answered from, so these tests
are about what must *not* come back: another document's chunk, or — the case
that would be worst in production — the whole library because a `set` arrived
empty. `doc` and `set` name documents explicitly; `all` is the only scope that
means "everything", and it has to be asked for by name.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.rag.retrieve import Scope, retrieve
from retrieval_support import (
    BERT,
    PAPER,
    BagOfWordsEmbedder,
    bert_chunks,
    load_document,
)

TRANSFORMER = "doc-transformer"
BERT_DOC = "doc-bert"


@pytest.fixture
async def two_docs(session: Any, paper_chunks: list[Any]) -> Any:
    transformer = await load_document(session, PAPER, TRANSFORMER, paper_chunks)
    bert = await load_document(session, BERT, BERT_DOC, bert_chunks())
    return session, transformer, bert


async def test_doc_scope_does_not_leak_another_document(two_docs: Any) -> None:
    """A `doc` scope must not return another document's chunk, even a better match."""
    session, transformer, _bert = two_docs
    result = await retrieve(
        session, "attention is all you need", Scope("doc", [transformer]), BagOfWordsEmbedder()
    )
    assert result.hits
    assert {hit.doc_id for hit in result.hits} == {transformer}


async def test_set_scope_searches_several_documents(two_docs: Any) -> None:
    session, transformer, bert = two_docs
    result = await retrieve(
        session, "bidirectional encoder", Scope("set", [transformer, bert]), BagOfWordsEmbedder()
    )
    assert {hit.doc_id for hit in result.hits} == {transformer, bert}


async def test_all_scope_searches_the_library(two_docs: Any) -> None:
    session, transformer, bert = two_docs
    result = await retrieve(session, "pre-training", Scope("all", []), BagOfWordsEmbedder())
    assert {hit.doc_id for hit in result.hits} == {transformer, bert}


async def test_a_single_document_scope_returns_only_that_document(two_docs: Any) -> None:
    """The reader's "ask this paper" must never answer from a neighbour."""
    session, _transformer, bert = two_docs
    result = await retrieve(session, "attention", Scope("doc", [bert]), BagOfWordsEmbedder())
    assert result.hits
    assert {hit.doc_id for hit in result.hits} == {bert}


async def test_an_empty_scope_returns_nothing(two_docs: Any) -> None:
    """An empty `doc`/`set` is a client bug, not a request for the whole library."""
    session, _transformer, _bert = two_docs
    for scope in (Scope("doc", []), Scope("set", [])):
        result = await retrieve(session, "attention", scope, BagOfWordsEmbedder())
        assert result.hits == []
        assert result.stages["bm25"] == 0
        assert result.stages["vector"] == 0


async def test_scope_describes_itself_in_the_result(two_docs: Any) -> None:
    """The response says which scope produced it, for the UI's provenance panel."""
    session, transformer, _bert = two_docs
    result = await retrieve(session, "attention", Scope("doc", [transformer]), BagOfWordsEmbedder())
    assert result.scope == {"type": "doc", "doc_ids": [transformer]}
