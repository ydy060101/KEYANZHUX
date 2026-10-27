"""T3.3: evidence-constrained QA, refusal, anchors and the SSE endpoint.

The acceptance numbers (anchor page accuracy, refusal rate on the real
reranker) are measured by `tools/check_qa.py`; these tests pin the mechanics
with deterministic doubles, in particular that no sentence reaches the client
before H04 has checked it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.llm.errors import LLMUnavailable
from app.models.orm import Block
from app.models.schemas import Anchor
from app.qa.answer import QaOutcome, _anchor, run_qa
from app.qa.prompt import Evidence
from app.qa.schemas import Citation, QAAnswer
from app.rag.retrieve import Scope
from qa_support import (
    DOC,
    TITLE,
    FailingExtractionGateway,
    QaGateway,
    ScoredEmbedder,
    evidence_number,
    load_qa_corpus,
)
from retrieval_support import BagOfWordsEmbedder

WARMUP_Q = "How many warmup steps does the learning rate schedule use?"
WARMUP_NEEDLE = "warmup_steps = 4000"


@pytest.fixture
async def corpus(session: Any, paper_parse: Any, paper_chunks: list[Any]) -> Any:
    await load_qa_corpus(session, paper_parse.model, paper_chunks)
    return session


def _warmup_answer(prompt: str) -> str:
    number = evidence_number(prompt, WARMUP_NEEDLE)
    return f"The learning rate schedule uses 4000 warmup steps [{number}]."


async def _ask(corpus: Any, gateway: QaGateway, embedder: Any, question: str = WARMUP_Q) -> QaOutcome:
    # A wide limit keeps the fixture's answering chunk in evidence even for the
    # BM25-only stub, so the tests measure verification rather than rank luck.
    return await run_qa(
        corpus, question, Scope("doc", [DOC]), embedder=embedder, gateway=gateway, limit=30
    )


# ---- anchors and streaming ----------------------------------------------


async def test_the_answer_cites_the_block_that_holds_the_number(corpus: Any) -> None:
    outcome = await _ask(corpus, QaGateway(_warmup_answer), ScoredEmbedder(0.9))
    assert outcome.answer.refused is False
    assert outcome.answer.citations, outcome.answer.flags
    citation = outcome.answer.citations[0]
    row = (
        await corpus.scalars(
            select(Block).where(Block.doc_id == DOC, Block.id == citation.anchor.block_id)
        )
    ).one()
    assert citation.anchor.doc_id == DOC
    assert citation.anchor.page == row.page == 7
    assert citation.anchor.bbox == list(row.bbox)
    assert WARMUP_NEEDLE in row.text


def test_the_anchor_prefers_the_block_holding_the_rare_number() -> None:
    """A chunk spanning a page break must anchor where its answer is.

    q17 on the fixture: the chunk opens with page 6's "...larger WMT" and the
    answer "36M sentences" is on page 7. Counting matches picked page 6 on a
    tie; weighting by rarity picks the block with the number that occurs once.
    """
    evidence = Evidence(
        number=1,
        chunk_id="c",
        doc_id=DOC,
        doc_title=TITLE,
        page_start=6,
        page_end=7,
        text=(
            "We trained on the WMT 2014 English-German dataset. "
            "The WMT 2014 English-French set has 36M sentences."
        ),
        block_ids=("b6", "b7"),
    )
    blocks = {
        (DOC, "b6"): Block(
            doc_id=DOC,
            id="b6",
            type="paragraph",
            page=6,
            bbox=[0, 0, 1, 1],
            reading_order=1,
            text="We trained on the WMT 2014 English-German dataset.",
        ),
        (DOC, "b7"): Block(
            doc_id=DOC,
            id="b7",
            type="paragraph",
            page=7,
            bbox=[0, 0, 2, 2],
            reading_order=2,
            text="The WMT 2014 English-French set has 36M sentences.",
        ),
    }
    anchor = _anchor("The WMT 2014 English-French set has 36M sentences.", evidence, blocks)
    assert anchor is not None
    assert anchor.page == 7
    assert anchor.block_id == "b7"


async def test_token_events_reconstruct_the_answer(corpus: Any) -> None:
    outcome = await _ask(corpus, QaGateway(_warmup_answer), ScoredEmbedder(0.9))
    streamed = "".join(data["text"] for name, data in outcome.events if name == "token")
    assert streamed == outcome.answer.answer


async def test_anchor_events_match_the_citations(corpus: Any) -> None:
    outcome = await _ask(corpus, QaGateway(_warmup_answer), ScoredEmbedder(0.9))
    events = {data["marker"]: data for name, data in outcome.events if name == "anchor"}
    assert set(events) == {citation.marker for citation in outcome.answer.citations}
    for citation in outcome.answer.citations:
        assert events[citation.marker]["anchor"] == citation.anchor.model_dump(mode="json")


async def test_every_citation_has_a_verbatim_quote(corpus: Any) -> None:
    outcome = await _ask(corpus, QaGateway(_warmup_answer), ScoredEmbedder(0.9))
    for citation in outcome.answer.citations:
        assert citation.quote
        assert len(citation.quote) <= 200


async def test_the_stream_ends_with_done(corpus: Any) -> None:
    outcome = await _ask(corpus, QaGateway(_warmup_answer), ScoredEmbedder(0.9))
    name, data = outcome.events[-1]
    assert name == "done"
    assert data["answer"] == outcome.answer.answer
    assert data["refused"] is False


# ---- refusal -------------------------------------------------------------


async def test_a_low_rerank_score_refuses_before_calling_the_model(corpus: Any) -> None:
    gateway = QaGateway(_warmup_answer)
    outcome = await _ask(corpus, gateway, ScoredEmbedder(0.01))
    assert outcome.answer.refused is True
    assert outcome.answer.citations == []
    assert "未在所选文献中找到依据" in outcome.answer.answer
    assert any(flag.kind == "weak_support" and "阈值" in flag.text for flag in outcome.answer.flags)
    assert gateway.calls == []


async def test_the_model_saying_not_found_is_a_refusal(corpus: Any) -> None:
    outcome = await _ask(corpus, QaGateway("NOT_FOUND"), ScoredEmbedder(0.9))
    assert outcome.answer.refused is True
    assert outcome.answer.flags[0].kind == "weak_support"


async def test_unverifiable_sentences_turn_the_whole_answer_into_a_refusal(corpus: Any) -> None:
    def reply(prompt: str) -> str:
        number = evidence_number(prompt, WARMUP_NEEDLE)
        return f"The schedule uses 5000 warmup steps [{number}]."

    outcome = await _ask(corpus, QaGateway(reply), ScoredEmbedder(0.9))
    assert outcome.answer.refused is True
    assert outcome.answer.citations == []
    assert any("5000" in flag.text for flag in outcome.answer.flags)


async def test_a_missing_reranker_answers_but_flags_the_degradation(corpus: Any) -> None:
    outcome = await _ask(corpus, QaGateway(_warmup_answer), BagOfWordsEmbedder())
    assert outcome.answer.refused is False
    assert any("重排模型不可用" in flag.text for flag in outcome.answer.flags)


# ---- H04 in the pipeline -------------------------------------------------


async def test_an_uncited_sentence_never_reaches_the_client(corpus: Any) -> None:
    def reply(prompt: str) -> str:
        number = evidence_number(prompt, WARMUP_NEEDLE)
        return f"The schedule uses 4000 warmup steps [{number}]. It is clearly the best model."

    outcome = await _ask(corpus, QaGateway(reply), ScoredEmbedder(0.9))
    assert "clearly the best" not in outcome.answer.answer
    assert "clearly the best" not in "".join(
        data["text"] for name, data in outcome.events if name == "token"
    )
    assert any(flag.kind == "uncited_claim" for flag in outcome.answer.flags)


async def test_an_invalid_marker_never_appears_in_the_answer(corpus: Any) -> None:
    def reply(prompt: str) -> str:
        number = evidence_number(prompt, WARMUP_NEEDLE)
        return f"The schedule uses 4000 steps [{number}][99]."

    outcome = await _ask(corpus, QaGateway(reply), ScoredEmbedder(0.9))
    assert "[99]" not in outcome.answer.answer
    assert any(flag.kind == "invalid_citation" for flag in outcome.answer.flags)


# ---- targeted extraction -------------------------------------------------


def _extraction(prompt: str) -> dict[str, Any]:
    number = evidence_number(prompt, "Adam optimizer")
    return {
        "fields": [
            {"name": "optimizer", "value": "Adam", "evidence": number},
            {"name": "beta2", "value": "0.98", "evidence": number},
            {"name": "beta1", "value": "LAMB", "evidence": number},
        ]
    }


async def test_metadata_questions_extract_grounded_fields_first(corpus: Any) -> None:
    def reply(prompt: str) -> str:
        number = evidence_number(prompt, "β2 = 0.98")
        return f"The optimizer is Adam with β2 = 0.98 [{number}]."

    question = "What optimizer and beta values were used for training?"
    gateway = QaGateway(reply, extraction=_extraction)
    outcome = await _ask(corpus, gateway, ScoredEmbedder(0.9), question)

    assert outcome.answer.refused is False
    assert outcome.stages["fields_extracted"] == 3
    assert outcome.stages["fields_grounded"] == 2
    assert [call["kind"] for call in gateway.calls] == ["json", "chat"]
    assert gateway.calls[0]["tier"] == "fast"
    assert gateway.calls[1]["tier"] == "strong"
    generation_prompt = gateway.calls[1]["messages"][-1]["content"]
    assert 'optimizer: "Adam"' in generation_prompt
    assert 'beta2: "0.98"' in generation_prompt
    assert "LAMB" not in generation_prompt


async def test_a_plain_question_skips_extraction(corpus: Any) -> None:
    def reply(prompt: str) -> str:
        number = evidence_number(prompt, "positional encodings")
        return f"Positional information is added as positional encodings [{number}]."

    gateway = QaGateway(reply)
    await _ask(corpus, gateway, ScoredEmbedder(0.9), "How is positional information injected?")
    assert [call["kind"] for call in gateway.calls] == ["chat"]


async def test_extraction_failure_degrades_to_plain_generation(corpus: Any) -> None:
    def reply(prompt: str) -> str:
        number = evidence_number(prompt, "Adam optimizer")
        return f"The optimizer is Adam [{number}]."

    gateway = FailingExtractionGateway(reply)
    outcome = await _ask(corpus, gateway, ScoredEmbedder(0.9), "What optimizer was used?")
    assert outcome.answer.refused is False
    assert outcome.stages["fields_grounded"] == 0
    assert gateway.calls[-1]["kind"] == "chat"


# ---- the endpoint --------------------------------------------------------


def _outcome() -> QaOutcome:
    anchor = Anchor(doc_id=DOC, block_id="b1_1", page=1, bbox=[0.0, 0.0, 1.0, 1.0])
    answer = QAAnswer(
        answer="A [1].",
        citations=[Citation(marker="[1]", anchor=anchor, quote="q")],
        refused=False,
        flags=[],
    )
    events: list[tuple[str, dict[str, Any]]] = [
        ("token", {"text": "A [1]."}),
        ("anchor", {"marker": "[1]", "anchor": anchor.model_dump(mode="json"), "quote": "q"}),
        ("done", answer.as_dict()),
    ]
    return QaOutcome(answer=answer, events=events, stages={})


@pytest.fixture
async def app_client() -> AsyncIterator[AsyncClient]:
    from app.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def test_the_endpoint_streams_token_anchor_done(
    session: Any, app_client: AsyncClient, monkeypatch: Any
) -> None:
    import app.api.qa as qa_api

    async def fake_run(session_: Any, question: str, scope: Scope) -> QaOutcome:
        return _outcome()

    monkeypatch.setattr(qa_api, "run_qa", fake_run)
    response = await app_client.post(
        "/api/v1/qa", json={"question": "hi", "scope": {"type": "doc", "doc_ids": [DOC]}}
    )
    assert response.status_code == 200
    assert "event: token" in response.text
    assert "event: anchor" in response.text
    assert "event: done" in response.text


async def test_the_endpoint_reports_a_model_failure_as_an_event(
    session: Any, app_client: AsyncClient, monkeypatch: Any
) -> None:
    import app.api.qa as qa_api

    async def failing(session_: Any, question: str, scope: Scope) -> QaOutcome:
        raise LLMUnavailable("provider down")

    monkeypatch.setattr(qa_api, "run_qa", failing)
    response = await app_client.post(
        "/api/v1/qa", json={"question": "hi", "scope": {"type": "doc", "doc_ids": [DOC]}}
    )
    assert "event: error" in response.text
    assert "llm_unavailable" in response.text


async def test_compare_mode_is_not_silently_answered(session: Any, app_client: AsyncClient) -> None:
    response = await app_client.post(
        "/api/v1/qa",
        json={"question": "hi", "scope": {"type": "doc", "doc_ids": [DOC]}, "mode": "compare"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "mode_not_implemented"
