"""T3.4: multi-document comparison, one cell at a time.

The doubles here are prompt-aware like the QA ones: the cell reply cites the
block that holds the needle, so the tests measure the anchoring and the H04
gate rather than a fixed rank order. BERT is parsed locally because only this
module compares two real papers; the Transformer fixtures come from conftest.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.errors import InvalidRequest
from app.ingest.parser import parse_pdf
from app.llm.errors import LLMUnavailable
from app.models.orm import Block, Document
from app.models.schemas import Anchor
from app.qa.answer import QaOutcome
from app.qa.compare import DEFAULT_DIMENSIONS, NOT_FOUND, run_compare
from app.qa.schemas import CompareCell, CompareRow, CompareTable, QAAnswer
from app.rag.chunk import Chunker
from app.rag.index import write_index
from app.rag.retrieve import Scope
from app.workers.persist import persist_parse
from qa_support import DOC, ScoredEmbedder, evidence_number, load_qa_corpus

BERT = "doc-bert"
BERT_TITLE = "BERT"
LAYERS = "number of layers"
MLM = "masked language model"

# (dimension, needle in the evidence block) -> the verbatim cell value.
_DEFAULTS = {
    (LAYERS, "N = 6"): "N = 6",
    (LAYERS, "L=12"): "L=12",
    (MLM, "masked language model"): "masked language model",
}


class CompareGateway:
    """Proposes dimensions, then fills cells from the block holding a needle."""

    def __init__(
        self,
        dimensions: tuple[str, ...] = (LAYERS,),
        *,
        values: dict[tuple[str, str], str] | None = None,
        dimension_error: Exception | None = None,
        cell_error: Exception | None = None,
        override_evidence: tuple[str, str, int] | None = None,
    ) -> None:
        self._dimensions = dimensions
        self._values = _DEFAULTS if values is None else values
        self._dimension_error = dimension_error
        self._cell_error = cell_error
        self._override = override_evidence
        self.calls: list[dict[str, Any]] = []

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        schema: Any,
        *,
        tier: str = "fast",
        temperature: float = 0.0,
        cache_prefix: str | None = None,
    ) -> Any:
        self.calls.append({"schema": schema.__name__, "tier": tier})
        prompt = messages[-1]["content"]
        if schema.__name__ == "_DimensionPlan":
            if self._dimension_error is not None:
                raise self._dimension_error
            return schema.model_validate({"dimensions": list(self._dimensions)})
        assert schema.__name__ == "_CellValue", schema.__name__
        if self._cell_error is not None:
            raise self._cell_error
        for (dimension, needle), value in self._values.items():
            if dimension not in prompt:
                continue
            try:
                number = evidence_number(prompt, needle)
            except AssertionError:
                continue
            if self._override is not None and self._override[:2] == (dimension, needle):
                number = self._override[2]
            return schema.model_validate({"value": value, "evidence": number})
        return schema.model_validate({"value": None, "evidence": None})


@pytest.fixture(scope="module")
def bert_model() -> Any:
    path = Path(__file__).resolve().parent.parent / "fixtures" / "pdf" / "1810.04805_bert.pdf"
    if not path.is_file():
        pytest.skip("1810.04805_bert.pdf is not staged")
    return parse_pdf(path, BERT).model


@pytest.fixture(scope="module")
def bert_chunks(bert_model: Any) -> list[Any]:
    chunker = Chunker()
    return chunker.feed(bert_model.blocks) + chunker.flush()


@pytest.fixture
async def corpora(
    session: Any,
    paper_parse: Any,
    paper_chunks: list[Any],
    bert_model: Any,
    bert_chunks: list[Any],
) -> Any:
    await load_qa_corpus(session, paper_parse.model, paper_chunks)
    session.add(
        Document(
            id=BERT,
            sha256="b" * 64,
            title=BERT_TITLE,
            status="ready",
            page_count=bert_model.page_count,
            file_path="bert.pdf",
        )
    )
    await session.flush()
    await persist_parse(session, bert_model)
    await write_index(session, BERT, bert_model.blocks, bert_model.outline, bert_chunks)
    await session.commit()
    return session


async def _compare(
    corpora: Any,
    gateway: CompareGateway,
    question: str = "Compare the number of layers in these two papers.",
) -> QaOutcome:
    return await run_compare(
        corpora,
        question,
        Scope("set", [DOC, BERT]),
        embedder=ScoredEmbedder(0.9),
        gateway=gateway,
    )


# ---- grounded cells ------------------------------------------------------


async def test_each_grounded_cell_carries_an_anchor_to_the_block_holding_it(corpora: Any) -> None:
    outcome = await _compare(corpora, CompareGateway())
    assert outcome.table is not None
    row = outcome.table.table[0]
    assert row.dimension == LAYERS
    assert row.cells[DOC].text == "N = 6"
    assert row.cells[BERT].text == "L=12"

    expected = {DOC: (2, "N = 6"), BERT: (3, "L=12")}
    for doc_id, (page, needle) in expected.items():
        cell = row.cells[doc_id]
        assert len(cell.citations) == 1
        anchor = cell.citations[0]
        assert anchor.doc_id == doc_id
        assert anchor.page == page
        block = (
            await corpora.scalars(
                select(Block).where(Block.doc_id == doc_id, Block.id == anchor.block_id)
            )
        ).one()
        assert needle in block.text
        assert anchor.bbox == list(block.bbox)


async def test_a_cell_without_evidence_is_not_found_without_an_anchor(corpora: Any) -> None:
    outcome = await _compare(corpora, CompareGateway((LAYERS, MLM)))
    assert outcome.table is not None
    mlm = outcome.table.table[1]
    assert mlm.cells[DOC].text == NOT_FOUND
    assert mlm.cells[DOC].citations == []
    assert mlm.cells[BERT].text == MLM
    assert mlm.cells[BERT].citations


async def test_the_summary_counts_the_table(corpora: Any) -> None:
    outcome = await _compare(
        corpora,
        CompareGateway((LAYERS, MLM)),
        question="Compare the two papers.",
    )
    assert outcome.table is not None
    assert "Compared 2 papers on 2 dimensions: 3/4 cells have source evidence." in outcome.table.summary
    assert outcome.answer.refused is False


async def test_the_summary_follows_the_question_language(corpora: Any) -> None:
    outcome = await _compare(corpora, CompareGateway(), question="比较这两篇论文的层数。")
    assert outcome.table is not None
    assert "比较了 2 篇文献的 1 个维度：2/2 个单元格有原文依据。" in outcome.table.summary


# ---- H04 and resilience --------------------------------------------------


async def test_a_value_not_present_in_the_cited_block_is_dropped(corpora: Any) -> None:
    gateway = CompareGateway(values={(LAYERS, "L=12"): "18 layers"})
    outcome = await _compare(corpora, gateway)
    assert outcome.table is not None
    cell = outcome.table.table[0].cells[BERT]
    assert cell.text == NOT_FOUND
    assert cell.citations == []
    assert any(flag.kind == "ungrounded_number" and BERT_TITLE in flag.text for flag in outcome.table.flags)


async def test_a_number_that_is_only_a_substring_is_dropped(corpora: Any) -> None:
    # BERT's page-3 block has "H=768"; "76" is not a value the paper states.
    gateway = CompareGateway(values={(LAYERS, "L=12"): "76"})
    outcome = await _compare(corpora, gateway)
    assert outcome.table is not None
    assert outcome.table.table[0].cells[BERT].text == NOT_FOUND


async def test_an_evidence_number_out_of_range_is_not_found(corpora: Any) -> None:
    gateway = CompareGateway(override_evidence=(LAYERS, "L=12", 99))
    outcome = await _compare(corpora, gateway)
    assert outcome.table is not None
    assert outcome.table.table[0].cells[BERT].text == NOT_FOUND


async def test_a_cell_extraction_failure_is_not_found_and_the_table_survives(corpora: Any) -> None:
    outcome = await _compare(corpora, CompareGateway(cell_error=LLMUnavailable("down")))
    assert outcome.table is not None
    assert all(
        cell.text == NOT_FOUND for row in outcome.table.table for cell in row.cells.values()
    )
    assert outcome.answer.refused is True
    assert outcome.answer.answer.startswith("未在所选文献中找到依据")
    assert any("提取失败" in flag.text for flag in outcome.table.flags)


async def test_dimension_failure_falls_back_to_the_default_set(corpora: Any) -> None:
    outcome = await _compare(corpora, CompareGateway(dimension_error=LLMUnavailable("down")))
    assert outcome.table is not None
    assert outcome.table.dimensions == DEFAULT_DIMENSIONS
    assert any("默认维度" in flag.text for flag in outcome.table.flags)


# ---- scope ---------------------------------------------------------------


async def test_one_document_is_not_a_comparison(corpora: Any) -> None:
    with pytest.raises(InvalidRequest) as caught:
        await run_compare(corpora, "Compare.", Scope("doc", [DOC]), gateway=CompareGateway())
    assert caught.value.code == "compare_needs_two_documents"


async def test_missing_documents_are_flagged_not_silently_dropped(corpora: Any) -> None:
    outcome = await run_compare(
        corpora,
        "Compare the number of layers.",
        Scope("set", [DOC, BERT, "doc-missing"]),
        embedder=ScoredEmbedder(0.9),
        gateway=CompareGateway(),
    )
    assert outcome.table is not None
    assert len(outcome.table.table[0].cells) == 2
    assert any("doc-missing" in flag.text for flag in outcome.table.flags)


# ---- the endpoint --------------------------------------------------------


def _outcome() -> QaOutcome:
    anchor = Anchor(doc_id=DOC, block_id="b2_12", page=2, bbox=[0.0, 0.0, 1.0, 1.0])
    table = CompareTable(
        dimensions=[LAYERS],
        table=[CompareRow(dimension=LAYERS, cells={DOC: CompareCell(text="N = 6", citations=[anchor])})],
        summary="Compared 1 paper.",
    )
    answer = QAAnswer(answer=table.summary, refused=False)
    payload = {**answer.as_dict(), "table": table.as_dict()}
    events: list[tuple[str, dict[str, Any]]] = [
        ("token", {"text": table.summary}),
        ("done", payload),
    ]
    return QaOutcome(answer=answer, events=events, stages={}, table=table)


@pytest.fixture
async def app_client() -> AsyncIterator[AsyncClient]:
    from app.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def test_the_endpoint_streams_a_compare_table(
    session: Any, app_client: AsyncClient, monkeypatch: Any
) -> None:
    import app.api.qa as qa_api

    async def fake_compare(session_: Any, question: str, scope: Scope) -> QaOutcome:
        return _outcome()

    monkeypatch.setattr(qa_api, "run_compare", fake_compare)
    response = await app_client.post(
        "/api/v1/qa",
        json={
            "question": "Compare.",
            "scope": {"type": "doc", "doc_ids": [DOC]},
            "mode": "compare",
        },
    )
    assert response.status_code == 200
    assert "event: token" in response.text
    assert "event: done" in response.text
    assert '"table"' in response.text
    assert "N = 6" in response.text


async def test_compare_with_one_document_reports_a_client_error_event(
    corpora: Any, app_client: AsyncClient
) -> None:
    response = await app_client.post(
        "/api/v1/qa",
        json={
            "question": "Compare.",
            "scope": {"type": "doc", "doc_ids": [DOC]},
            "mode": "compare",
        },
    )
    assert response.status_code == 200
    assert "event: error" in response.text
    assert "compare_needs_two_documents" in response.text
