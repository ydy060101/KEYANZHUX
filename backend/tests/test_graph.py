"""T6.1/T6.2 acceptance: reference matching, graph metrics, graph endpoints.

The matching rules must be testable without a PDF (T6.1 constraint), so the
first block exercises `matching.py` directly. The metric block uses tiny graphs
whose PageRank and betweenness can be checked by hand. The last block builds a
graph from real `ReferenceRow`s and follows the job through `queue.execute`,
exactly as the worker would.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.graph.matching import Candidate, match_reference, title_similarity
from app.graph.service import assign_roles, betweenness, build_graph, page_rank

ATTENTION = Candidate(
    id="doc-a", title="Attention Is All You Need", arxiv_id="1706.03762", doi="10.1000/attention", year=2017
)
RESNET = Candidate(
    id="doc-b",
    title="Deep Residual Learning for Image Recognition",
    arxiv_id="1512.03385",
    doi=None,
    year=2015,
)
CANDS = [ATTENTION, RESNET]


def test_matching_order_is_doi_then_arxiv_then_title() -> None:
    arxiv = match_reference("Vaswani, A. Attention is all you need. arXiv:1706.03762v5, 2017.", CANDS)
    assert arxiv is not None and arxiv.method == "arxiv_id" and arxiv.target_id == "doc-a"

    doi = match_reference("Vaswani, A. Attention is all you need. DOI: 10.1000/ATTENTION, 2017.", CANDS)
    assert doi is not None and doi.method == "doi" and doi.target_id == "doc-a"

    title = match_reference("Vaswani, A. Attention is all you need. In NeurIPS, 2017.", CANDS)
    assert title is not None and title.method == "title"
    assert title.confidence == 1.0


def test_title_similarity_is_the_share_of_title_tokens_present() -> None:
    assert title_similarity("Attention Is All You Need", "Vaswani. Attention is all you need. 2017.") == 1.0
    partial = title_similarity("Attention Is All You Need", "Attention mechanisms in neural machines")
    assert partial == 0.25, "only one of the four title tokens occurs"
    assert title_similarity("", "anything") == 0.0


def test_an_unrelated_reference_does_not_match() -> None:
    assert match_reference("Kingma, D. Adam: a method for stochastic optimization. 2015.", CANDS) is None


def test_a_year_conflict_vetoes_the_title_match() -> None:
    """Both sides know a year and disagree: it is another paper."""
    assert match_reference("Vaswani, A. Attention is all you need. 2019.", CANDS) is None


def test_page_rank_prefers_the_most_cited_node() -> None:
    nodes = ["a", "b", "c"]
    edges = [
        {"source": "a", "target": "b"},
        {"source": "a", "target": "c"},
        {"source": "b", "target": "c"},
    ]
    ranks = page_rank(nodes, edges)
    assert ranks["c"] > ranks["b"] > ranks["a"]
    assert abs(sum(ranks.values()) - 1.0) < 1e-5
    assert page_rank(nodes, edges) == ranks, "same input, same output (H06)"


def test_betweenness_marks_the_only_bridge_on_a_path() -> None:
    nodes = ["a", "b", "c"]
    edges = [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}]
    scores = betweenness(nodes, edges)
    assert scores["b"] == 1.0, "b lies on the only pair (a, c), so it is 100 % of them"
    assert scores["a"] == 0.0 and scores["c"] == 0.0

    path = ["a", "b", "c", "d"]
    line = [{"source": u, "target": v} for u, v in zip(path, path[1:], strict=False)]
    longer = betweenness(path, line)
    assert longer["b"] == longer["c"] == round(2 / 3, 6)
    assert longer["a"] == longer["d"] == 0.0


def test_roles_follow_the_architecture_rule() -> None:
    nodes = [
        {"id": "hub", "pagerank": 0.6, "in_degree": 3, "out_degree": 1},
        {"id": "leaf", "pagerank": 0.1, "in_degree": 0, "out_degree": 2},
        {"id": "mid", "pagerank": 0.3, "in_degree": 1, "out_degree": 1},
    ]
    assign_roles(nodes)
    roles = {node["id"]: (node["role"], node["reason"]) for node in nodes}
    assert roles["hub"][0] == "cornerstone"
    assert "入度 3" in roles["hub"][1]
    assert roles["leaf"][0] == "peripheral"
    assert "入度 0" in roles["leaf"][1]
    assert roles["mid"][0] == "middle"


def test_the_top_ranked_node_without_two_citations_is_not_cornerstone() -> None:
    nodes = [
        {"id": "high", "pagerank": 0.5, "in_degree": 1, "out_degree": 1},
        {"id": "low", "pagerank": 0.1, "in_degree": 1, "out_degree": 1},
        {"id": "leaf", "pagerank": 0.4, "in_degree": 0, "out_degree": 1},
    ]
    assign_roles(nodes)
    assert next(node for node in nodes if node["id"] == "high")["role"] == "middle"


def _doc(
    doc_id: str,
    title: str,
    *,
    arxiv_id: str | None = None,
    year: int | None = None,
    status: str = "ready",
) -> Any:
    from app.models.orm import Document

    return Document(
        id=doc_id,
        sha256=(doc_id + "0" * 64)[:64],
        title=title,
        arxiv_id=arxiv_id,
        status=status,
        file_path=f"{doc_id}.pdf",
        created_by="default",
        meta={"year": year, "doi": None},
    )


def _refs(doc_id: str, raws: list[str]) -> list[Any]:
    from app.models.orm import ReferenceRow

    return [
        ReferenceRow(id=f"{doc_id}:r{index}", doc_id=doc_id, index=index, raw=raw)
        for index, raw in enumerate(raws, start=1)
    ]


def _seed_library() -> list[Any]:
    return [
        _doc("doc-a", "Attention Is All You Need", arxiv_id="1706.03762", year=2017),
        _doc("doc-b", "Deep Residual Learning for Image Recognition", arxiv_id="1512.03385", year=2015),
        _doc("doc-c", "Generative Adversarial Networks", arxiv_id="1406.2661", year=2014),
        _doc("doc-d", "A Survey With No References"),
        *_refs(
            "doc-a",
            [
                "He, K. Deep Residual Learning for Image Recognition. arXiv:1512.03385, 2015.",
                "Kingma, D. Adam: a method for stochastic optimization. 2015.",
            ],
        ),
        *_refs("doc-b", ["Goodfellow, I. Generative adversarial networks. 2014."]),
    ]


async def test_build_graph_uses_identifiers_and_title_matching(session: Any) -> None:
    session.add_all(_seed_library())
    await session.commit()

    data = await build_graph(session, ["doc-a", "doc-b", "doc-c", "doc-d"])
    edges = {(edge["source"], edge["target"]): edge for edge in data["edges"]}

    assert set(edges) == {("doc-a", "doc-b"), ("doc-b", "doc-c")}
    assert edges[("doc-a", "doc-b")]["method"] == "arxiv_id"
    assert edges[("doc-b", "doc-c")]["method"] == "title"
    assert "Goodfellow" in edges[("doc-b", "doc-c")]["contexts"][0]
    assert data["metrics"]["unmatched_references"] == 1, "the Adam paper is not in the library"
    assert data["metrics"]["isolated"] == ["doc-d"], "a document without edges is not a node"
    assert {node["id"] for node in data["nodes"]} == {"doc-a", "doc-b", "doc-c"}
    assert data["metrics"]["node_count"] == 3

    again = await build_graph(session, ["doc-a", "doc-b", "doc-c", "doc-d"])
    assert again == data, "the same library must produce the same graph (H06)"


async def test_a_self_citation_never_becomes_an_edge(session: Any) -> None:
    session.add_all(
        [
            _doc("doc-a", "Attention Is All You Need", arxiv_id="1706.03762", year=2017),
            *_refs("doc-a", ["Vaswani, A. Attention is all you need. arXiv:1706.03762, 2017."]),
        ]
    )
    await session.commit()

    data = await build_graph(session, ["doc-a"])
    assert data["edges"] == []
    assert data["metrics"]["self_references"] == 1
    assert data["nodes"] == []


@pytest.fixture
async def client(session: Any) -> Any:
    from app.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_graph_endpoint_validates_the_selection(session: Any, client: AsyncClient) -> None:
    session.add_all([_doc("doc-a", "Attention Is All You Need"), _doc("doc-b", "Deep Residual", status="parsing")])
    await session.commit()

    alone = await client.post("/api/v1/graphs", json={"doc_ids": ["doc-a"]})
    assert alone.status_code == 400
    assert alone.json()["error"]["code"] == "invalid_request"

    duplicate = await client.post("/api/v1/graphs", json={"doc_ids": ["doc-a", "doc-a"]})
    assert duplicate.status_code == 400

    missing = await client.post("/api/v1/graphs", json={"doc_ids": ["doc-a", "nope"]})
    assert missing.status_code == 404

    unparsed = await client.post("/api/v1/graphs", json={"doc_ids": ["doc-a", "doc-b"]})
    assert unparsed.status_code == 409
    assert unparsed.json()["error"]["code"] == "conflict"


async def test_graph_job_persists_and_get_serves_arrays(session: Any, client: AsyncClient, monkeypatch: Any) -> None:
    import app.api.graphs as graphs_api
    from app.models.orm import Job
    from app.workers import queue

    async def fake_enqueue(job_id: str) -> bool:
        return True

    monkeypatch.setattr(graphs_api.queue, "enqueue", fake_enqueue)
    session.add_all(_seed_library())
    await session.commit()

    response = await client.post("/api/v1/graphs", json={"doc_ids": ["doc-a", "doc-b", "doc-c"]})
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["kind"] == "graph" and body["status"] == "queued"

    await queue.execute(body["id"])
    job = await session.get(Job, body["id"])
    assert job is not None
    await session.refresh(job)
    assert job.status == "succeeded", job.error
    assert job.result["node_count"] == 3 and job.result["edge_count"] == 2

    graph = await client.get(f"/api/v1/graphs/{job.result['graph_id']}")
    assert graph.status_code == 200, graph.text
    payload = graph.json()
    assert isinstance(payload["nodes"], list), "the contract answers GraphNode[], not a dict"
    assert isinstance(payload["edges"], list)
    assert graph.json()["nodes"][0]["role"] in {"cornerstone", "middle", "peripheral"}
    assert graph.json()["metrics"]["pagerank_damping"] == 0.85

    missing = await client.get("/api/v1/graphs/not-a-graph")
    assert missing.status_code == 404
