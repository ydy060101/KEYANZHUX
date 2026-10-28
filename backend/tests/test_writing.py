"""T7.1 acceptance: outline generation, verification and BibTeX.

No test reaches the network: the search and verification steps are replaced
with fixed candidates, and the LLM with a scripted gateway. The point is the
guarantee, not the prose — an unverified reference must never reach the list
or the BibTeX, and a citation key the model invented must not survive.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.discover.sources import Candidate
from app.writing import outline as outline_module
from app.writing import verify as verify_module
from app.writing.bibtex import to_bibtex
from app.writing.outline import OutlineDraft, OutlinePlan, SectionDraft, SectionPlan, assemble
from app.writing.verify import best_match, title_similarity

ATTENTION = {
    "key": "vaswani2017attention",
    "title": "Attention Is All You Need",
    "authors": ["Ashish Vaswani", "Noam Shazeer"],
    "year": 2017,
    "doi": "10.1000/attention",
    "arxiv_id": "1706.03762",
    "source_url": "https://doi.org/10.1000/attention",
    "status": "verified",
    "similarity": 1.0,
}

CANDIDATE = Candidate(
    source="crossref",
    ext_id="10.1000/attention",
    title="Attention Is All You Need",
    authors=["Ashish Vaswani"],
    year=2017,
    doi="10.1000/attention",
)


def test_title_similarity_handles_subtitles_and_short_titles() -> None:
    assert title_similarity("Attention Is All You Need", "Attention Is All You Need") == 1.0
    assert title_similarity("Attention Is All You Need", "Attention Is All You Need (NeurIPS 2017)") == 1.0
    assert title_similarity("Attention Is All You Need", "Attention mechanisms in neural machines") == 0.2
    assert title_similarity("BERT", "BERT: Pre-training of Deep Bidirectional Transformers") == 0.0
    assert title_similarity("BERT", "BERT") == 1.0


def test_best_match_requires_year_and_author_agreement() -> None:
    wrong_year = Candidate(source="crossref", ext_id="x", title="Attention Is All You Need", year=2019)
    assert best_match("Attention Is All You Need", [wrong_year], year=2017) is None

    wrong_author = Candidate(
        source="crossref", ext_id="x", title="Attention Is All You Need", authors=["Jane Doe"], year=2017
    )
    assert best_match("Attention Is All You Need", [wrong_author], year=2017, authors=["Ashish Vaswani"]) is None

    match = best_match("Attention Is All You Need", [CANDIDATE], year=2017, authors=["Vaswani"])
    assert match is not None and match[0].doi == "10.1000/attention"


async def test_verify_titles_preserves_order_and_marks_misses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_verify(
        title: str, client: Any = None, *, year: int | None = None, authors: Any = ()
    ) -> tuple[Candidate, float] | None:
        return (CANDIDATE, 1.0) if title == "Attention Is All You Need" else None

    monkeypatch.setattr(verify_module, "verify_title", fake_verify)
    rows = await verify_module.verify_titles(["Attention Is All You Need", "Made Up Title"])
    assert [row["status"] for row in rows] == ["verified", "unverified"]
    assert rows[0]["doi"] == "10.1000/attention"
    assert rows[1] == {
        "title": "Made Up Title",
        "status": "unverified",
        "source_url": None,
        "arxiv_id": None,
        "doi": None,
    }


def test_bibtex_exports_verified_entries_only_with_unique_keys() -> None:
    duplicate = {**ATTENTION, "title": "Attention Again"}
    unverified = {
        "key": "ghost2099",
        "title": "An Invented Paper",
        "authors": ["Nobody"],
        "year": 2099,
        "status": "unverified",
    }
    text = to_bibtex([ATTENTION, unverified, duplicate])
    assert "An Invented Paper" not in text
    assert "Attention Is All You Need" in text
    assert "doi = {10.1000/attention}" in text
    assert len([line for line in text.splitlines() if line.startswith("@")]) == 2
    keys = [line.split("{", 1)[1].rstrip(",") for line in text.splitlines() if line.startswith("@")]
    assert len(keys) == len(set(keys))


def test_assemble_filters_invented_citations_and_fills_missing_sections() -> None:
    plan = OutlinePlan(title="Plan", sections=[SectionPlan(heading=heading) for heading in outline_module.HEADINGS])
    draft = OutlineDraft(
        title="A Study",
        sections=[
            SectionDraft(heading="## Abstract", markdown="Grounded \\cite{vaswani2017attention}."),
            SectionDraft(heading="Introduction", markdown="Invented \\cite{ghost2099}."),
        ],
    )
    markdown, sections = assemble(draft, plan, [ATTENTION])
    assert "\\cite{vaswani2017attention}" in markdown
    assert "ghost2099" not in markdown
    assert "Invented [待补充]." in markdown
    assert [section["heading"] for section in sections] == list(outline_module.HEADINGS)
    assert sections[2]["markdown"] == "[待补充]"


def test_assemble_accepts_chinese_section_headings() -> None:
    plan = OutlinePlan(title="Plan", sections=[SectionPlan(heading=heading) for heading in outline_module.HEADINGS])
    draft = OutlineDraft(
        title="A Study",
        sections=[
            SectionDraft(heading="摘要", markdown="研究摘要。"),
            SectionDraft(heading="1. 引言", markdown="研究引言。"),
            SectionDraft(heading="相关工作（Related Work）", markdown="相关工作。"),
        ],
    )
    markdown, sections = assemble(draft, plan, [])
    assert sections[0]["markdown"] == "研究摘要。"
    assert sections[1]["markdown"] == "研究引言。"
    assert sections[2]["markdown"] == "相关工作。"
    assert "## Related Work" in markdown


async def test_derive_queries_filters_numbering_and_non_english() -> None:
    from app.llm.types import ChatResult

    class TextGateway:
        async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> ChatResult:
            text = "1. retrieval augmented generation\nlong document question answering\n中文查询\nfour word query here"
            return ChatResult(text=text, model="fake")

    queries = await outline_module.derive_queries(TextGateway(), "一种方法")
    assert queries == [
        "retrieval augmented generation",
        "long document question answering",
        "four word query here",
    ]


async def test_search_candidates_drops_off_topic_results(monkeypatch: pytest.MonkeyPatch) -> None:
    on_topic = Candidate(
        source="crossref",
        ext_id="1",
        title="Retrieval-Augmented Generation for Question Answering",
        year=2023,
        doi="10.1/on",
    )
    off_topic = Candidate(source="crossref", ext_id="2", title="Web Survey Methodology", year=2023, doi="10.1/off")

    async def fake_search(query: str, client: Any, limit: int = 5) -> tuple[list[Candidate], dict[str, str]]:
        return [on_topic, off_topic], {}

    monkeypatch.setattr(outline_module, "search", fake_search)
    plan = OutlinePlan(
        title="Plan",
        sections=[],
        queries=["retrieval augmented generation question answering"],
    )
    found = await outline_module.search_candidates(plan, "检索增强问答")
    assert [candidate.title for candidate in found] == ["Retrieval-Augmented Generation for Question Answering"]


def test_assemble_accepts_the_providers_named_section_fields() -> None:
    plan = OutlinePlan(title="Plan", sections=[])
    draft = OutlineDraft(
        title="A Study", abstract="摘要正文。", introduction="引言正文。", related_work="相关工作正文。"
    )
    _markdown, sections = assemble(draft, plan, [])
    assert [section["markdown"] for section in sections] == ["摘要正文。", "引言正文。", "相关工作正文。"]


def test_claim_flags_mark_result_sentences() -> None:
    flags = outline_module.claim_flags(
        [
            {"heading": "Abstract", "markdown": "实验表明该方法有效。"},
            {"heading": "Introduction", "markdown": "We will evaluate the method."},
        ]
    )
    assert [flag["section"] for flag in flags] == ["Abstract"]
    assert flags[0]["kind"] == "unverified_claim"


def test_assemble_repairs_citations_that_lost_their_braces() -> None:
    reference = {
        **ATTENTION,
        "key": "benita2025retrieval",
        "authors": ["S. Sharon Benita"],
        "year": 2025,
        "title": "Retrieval Augmented Generation for Question Answering",
    }
    draft = OutlineDraft(
        title="T",
        abstract=r"Works \citebenita2025retrieval and \cite{benita2025retrieval}.",
    )
    markdown, _sections = assemble(draft, OutlinePlan(title="T", sections=[]), [reference])
    assert markdown.count(r"\cite{benita2025retrieval}") == 2
    assert r"\citebenita2025retrieval" not in markdown


class FakeGateway:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def chat_json(self, messages: list[dict[str, str]], schema: Any, **kwargs: Any) -> Any:
        self.calls.append(schema.__name__)
        assert kwargs.get("temperature") == 0.0
        if schema is OutlinePlan:
            return OutlinePlan(
                title="Verifiable Research",
                sections=[
                    SectionPlan(heading=heading, goal="goal", queries=["query"]) for heading in outline_module.HEADINGS
                ],
                queries=["retrieval augmented generation"],
            )
        return OutlineDraft(
            title="Verifiable Research",
            abstract="Grounded claim \\cite{vaswani2017attention}.",
            introduction="Unsupported \\cite{ghost2099}.",
        )


class FailingGateway:
    async def chat_json(self, messages: list[dict[str, str]], schema: Any, **kwargs: Any) -> Any:
        from app.llm.errors import LLMUnavailable

        raise LLMUnavailable("down")


@pytest.fixture
async def client(session: Any) -> AsyncIterator[AsyncClient]:
    from app.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _parse_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in text.strip().split("\n\n"):
        if not block or block.startswith(":"):
            continue
        name = ""
        data: dict[str, Any] | None = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                value: object = json.loads(line[6:])
                assert isinstance(value, dict)
                data = value
        if name and data is not None:
            events.append((name, data))
    return events


async def _fake_search(plan: OutlinePlan, idea: str, client: Any = None) -> list[Candidate]:
    return [CANDIDATE]


async def _fake_verify(candidates: list[Candidate], client: Any = None) -> list[dict[str, Any]]:
    return [ATTENTION]


async def _outline(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, gateway: Any = None
) -> list[tuple[str, dict[str, Any]]]:
    monkeypatch.setattr(outline_module, "get_gateway", lambda: gateway or FakeGateway())
    monkeypatch.setattr(outline_module, "search_candidates", _fake_search)
    monkeypatch.setattr(outline_module, "verify_candidates", _fake_verify)
    response = await client.post("/api/v1/writing/outline", json={"idea": "验证锚点的问答系统", "language": "zh"})
    assert response.status_code == 200, response.text
    return _parse_sse(response.text)


async def test_outline_streams_stages_and_persists_verified_draft(
    session: Any, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.models.orm import Draft

    events = await _outline(client, monkeypatch)
    stages = [data["stage"] for name, data in events if name == "stage"]
    assert stages == ["planning", "searching", "verifying", "writing"]
    done = next(data for name, data in events if name == "done")
    assert done["draft_id"]
    assert [ref["key"] for ref in done["references"]] == ["vaswani2017attention"]
    assert "ghost2099" not in done["outline"]["markdown"]
    assert "[待补充]" in done["outline"]["markdown"]
    assert len(done["outline"]["sections"]) == 3

    draft = await session.get(Draft, done["draft_id"])
    assert draft is not None
    assert draft.references["items"][0]["doi"] == "10.1000/attention"

    bibtex = await client.get(f"/api/v1/writing/drafts/{done['draft_id']}/bibtex")
    assert bibtex.status_code == 200
    assert "Attention Is All You Need" in bibtex.text
    assert "ghost2099" not in bibtex.text
    assert "Invented" not in bibtex.text


async def test_outline_reports_llm_failure_as_an_sse_error(
    session: Any, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = await _outline(client, monkeypatch, FailingGateway())
    assert events[-1][0] == "error"
    assert events[-1][1]["error"]["code"] == "llm_unavailable"


async def test_outline_rejects_a_blank_idea(client: AsyncClient) -> None:
    response = await client.post("/api/v1/writing/outline", json={"idea": "   "})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


async def test_verify_endpoint_returns_the_contract_shape(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(titles: list[str]) -> list[dict[str, Any]]:
        return [
            {"title": title, "status": "unverified", "source_url": None, "arxiv_id": None, "doi": None}
            for title in titles
        ]

    import app.api.writing as writing_api

    monkeypatch.setattr(writing_api, "verify_titles", fake)
    response = await client.post(
        "/api/v1/writing/references/verify", json={"titles": [" A Paper ", "A Paper", "Another"]}
    )
    assert response.status_code == 200
    body = response.json()
    assert [row["title"] for row in body] == ["A Paper", "Another"]
    assert all(set(row) == {"title", "status", "source_url", "arxiv_id", "doi"} for row in body)


async def test_verify_endpoint_rejects_blank_titles(client: AsyncClient) -> None:
    response = await client.post("/api/v1/writing/references/verify", json={"titles": ["  "]})
    assert response.status_code == 400


async def test_bibtex_of_a_missing_draft_is_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/writing/drafts/nope/bibtex")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
