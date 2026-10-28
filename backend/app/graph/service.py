"""Build and measure the citation graph (T6.1/T6.2).

Nodes are the selected documents that participate in at least one citation
edge; a document nobody cites and that cites nobody is reported in
`metrics.isolated` instead of becoming a node with a meaningless role. Edges
are u→v when u's bibliography matches v (see `matching.py`); an unmatched
reference never enters the graph.

Metrics are computed in pure Python so the result is deterministic and the
project keeps its dependency list: PageRank with damping 0.85 (power iteration
to 1e-9), Brandes betweenness on the undirected projection, and in/out degree.
Roles follow 01 §5.5: **cornerstone** = PageRank in the top 20 % *and* in-degree
≥ 2; **peripheral** = in-degree 0 with out-degree > 0; everything else middle.
Every role carries a one-line `reason` built from the numbers, never a model's
judgement.
"""

from __future__ import annotations

import math
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.orm import Document, Graph, ReferenceRow
from .matching import Candidate, match_reference

DAMPING = 0.85
MAX_ITER = 100
TOL = 1e-9
CORNERSTONE_TOP = 0.2
MAX_DOCS = 50
MAX_CONTEXTS = 3
CONTEXT_CHARS = 240


def doc_year(document: Document) -> int | None:
    """The parsed year, else the year encoded in the arXiv id (1706 → 2017)."""
    meta = document.meta or {}
    year = meta.get("year")
    if isinstance(year, int):
        return year
    if isinstance(year, str) and year.isdigit():
        return int(year)
    arxiv_id = document.arxiv_id or ""
    if len(arxiv_id) >= 2 and arxiv_id[:2].isdigit():
        return 2000 + int(arxiv_id[:2])
    return None


def page_rank(node_ids: list[str], edges: list[dict[str, Any]]) -> dict[str, float]:
    ids = sorted(node_ids)
    n = len(ids)
    if n == 0:
        return {}
    index = {node: i for i, node in enumerate(ids)}
    out_edges: list[list[int]] = [[] for _ in range(n)]
    for edge in edges:
        out_edges[index[edge["source"]]].append(index[edge["target"]])
    pr = [1.0 / n] * n
    for _ in range(MAX_ITER):
        dangling = sum(pr[i] for i in range(n) if not out_edges[i])
        base = (1.0 - DAMPING) / n + DAMPING * dangling / n
        new = [base] * n
        for u in range(n):
            if out_edges[u]:
                share = DAMPING * pr[u] / len(out_edges[u])
                for v in out_edges[u]:
                    new[v] += share
        delta = sum(abs(new[i] - pr[i]) for i in range(n))
        pr = new
        if delta < TOL:
            break
    return {node: round(pr[index[node]], 6) for node in ids}


def betweenness(node_ids: list[str], edges: list[dict[str, Any]]) -> dict[str, float]:
    """Brandes betweenness on the undirected projection, normalised."""
    ids = sorted(node_ids)
    n = len(ids)
    if n == 0:
        return {}
    adj: dict[str, list[str]] = {node: [] for node in ids}
    seen: set[tuple[str, str]] = set()
    for edge in edges:
        u, v = edge["source"], edge["target"]
        if u == v or (u, v) in seen or (v, u) in seen:
            continue
        seen.add((u, v))
        adj[u].append(v)
        adj[v].append(u)
    centrality = {node: 0.0 for node in ids}
    for source in ids:
        stack: list[str] = []
        predecessors: dict[str, list[str]] = {node: [] for node in ids}
        sigma = {node: 0.0 for node in ids}
        sigma[source] = 1.0
        distance = {node: -1 for node in ids}
        distance[source] = 0
        queue = [source]
        while queue:
            v = queue.pop(0)
            stack.append(v)
            for w in adj[v]:
                if distance[w] < 0:
                    distance[w] = distance[v] + 1
                    queue.append(w)
                if distance[w] == distance[v] + 1:
                    sigma[w] += sigma[v]
                    predecessors[w].append(v)
        delta = {node: 0.0 for node in ids}
        while stack:
            w = stack.pop()
            for v in predecessors[w]:
                delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w])
            if w != source:
                centrality[w] += delta[w]
    norm = ((n - 1) * (n - 2) / 2) if n > 2 else 1.0
    return {node: round(centrality[node] / 2.0 / norm, 6) for node in ids}


def assign_roles(nodes: list[dict[str, Any]]) -> None:
    ranked = sorted(nodes, key=lambda node: (-node["pagerank"], node["id"]))
    top = max(1, math.ceil(CORNERSTONE_TOP * len(ranked))) if ranked else 0
    top_ids = {node["id"] for node in ranked[:top]}
    for node in nodes:
        if node["id"] in top_ids and node["in_degree"] >= 2:
            node["role"] = "cornerstone"
            node["reason"] = f"PageRank 前 20%（{node['pagerank']:.3f}），入度 {node['in_degree']}"
        elif node["in_degree"] == 0 and node["out_degree"] > 0:
            node["role"] = "peripheral"
            node["reason"] = f"入度 0、出度 {node['out_degree']}：只引用他人"
        else:
            node["role"] = "middle"
            node["reason"] = f"入度 {node['in_degree']}、出度 {node['out_degree']}、PageRank {node['pagerank']:.3f}"


async def _load_documents(session: AsyncSession, doc_ids: list[str]) -> list[Document]:
    rows = (
        (await session.execute(select(Document).where(Document.id.in_(doc_ids), Document.status == "ready")))
        .scalars()
        .all()
    )
    order = {doc_id: position for position, doc_id in enumerate(doc_ids)}
    return sorted(rows, key=lambda doc: order.get(doc.id, len(order)))


async def _references(session: AsyncSession, doc_ids: list[str]) -> dict[str, list[tuple[int, str]]]:
    rows = (
        await session.execute(
            select(
                ReferenceRow.doc_id,
                # `index` is also a Row method; the label keeps the value reachable.
                ReferenceRow.index.label("ref_index"),
                ReferenceRow.raw,
            )
            .where(ReferenceRow.doc_id.in_(doc_ids))
            .order_by(ReferenceRow.doc_id, ReferenceRow.index)
        )
    ).all()
    grouped: dict[str, list[tuple[int, str]]] = {doc_id: [] for doc_id in doc_ids}
    for row in rows:
        grouped.setdefault(row.doc_id, []).append((row.ref_index, row.raw or ""))
    return grouped


def _candidates(docs: list[Document]) -> list[Candidate]:
    out: list[Candidate] = []
    for doc in docs:
        meta = doc.meta or {}
        doi = meta.get("doi")
        out.append(
            Candidate(
                id=doc.id,
                title=doc.title or "",
                arxiv_id=doc.arxiv_id,
                doi=doi if isinstance(doi, str) else None,
                year=doc_year(doc),
            )
        )
    return sorted(out, key=lambda candidate: candidate.id)


async def build_graph(session: AsyncSession, doc_ids: list[str]) -> dict[str, Any]:
    """Nodes, edges and metrics for the selected documents (no persistence)."""
    docs = await _load_documents(session, doc_ids)
    candidates = _candidates(docs)
    references = await _references(session, [doc.id for doc in docs])

    edges: dict[tuple[str, str], dict[str, Any]] = {}
    matched = unmatched = self_references = 0
    for doc in docs:
        for _index, raw in references.get(doc.id, []):
            match = match_reference(raw, candidates)
            if match is None:
                unmatched += 1
                continue
            if match.target_id == doc.id:
                self_references += 1
                continue
            matched += 1
            key = (doc.id, match.target_id)
            existing = edges.get(key)
            if existing is not None:
                if len(existing["contexts"]) < MAX_CONTEXTS:
                    existing["contexts"].append(raw[:CONTEXT_CHARS])
                continue
            edges[key] = {
                "source": doc.id,
                "target": match.target_id,
                "method": match.method,
                "confidence": match.confidence,
                "contexts": [raw[:CONTEXT_CHARS]],
            }

    node_ids = sorted({endpoint for key in edges for endpoint in key})
    in_degree = {node: 0 for node in node_ids}
    out_degree = {node: 0 for node in node_ids}
    for source, target in edges:
        out_degree[source] += 1
        in_degree[target] += 1
    edge_list = [edges[key] for key in sorted(edges)]
    pagerank = page_rank(node_ids, edge_list)
    bridge = betweenness(node_ids, edge_list)
    by_id = {doc.id: doc for doc in docs}
    nodes: list[dict[str, Any]] = []
    for node_id in node_ids:
        doc = by_id[node_id]
        nodes.append(
            {
                "id": node_id,
                "title": doc.title or node_id,
                "year": doc_year(doc),
                "role": "middle",
                "pagerank": pagerank.get(node_id, 0.0),
                "in_degree": in_degree[node_id],
                "out_degree": out_degree[node_id],
                "betweenness": bridge.get(node_id, 0.0),
                "reason": "",
            }
        )
    assign_roles(nodes)
    nodes.sort(key=lambda node: (-node["pagerank"], node["id"]))

    node_set = set(node_ids)
    isolated = [doc.id for doc in docs if doc.id not in node_set]
    method_counts: dict[str, int] = {}
    for edge in edge_list:
        method_counts[edge["method"]] = method_counts.get(edge["method"], 0) + 1
    metrics = {
        "node_count": len(nodes),
        "edge_count": len(edge_list),
        "matched_references": matched,
        "unmatched_references": unmatched,
        "self_references": self_references,
        "isolated": isolated,
        "method_counts": method_counts,
        "cornerstone": [node["id"] for node in nodes if node["role"] == "cornerstone"],
        "peripheral": [node["id"] for node in nodes if node["role"] == "peripheral"],
        "pagerank_damping": DAMPING,
    }
    return {"nodes": nodes, "edges": edge_list, "metrics": metrics}


async def create_graph(session: AsyncSession, doc_ids: list[str]) -> Graph:
    data = await build_graph(session, doc_ids)
    graph = Graph(
        doc_ids=list(doc_ids),
        nodes={node["id"]: node for node in data["nodes"]},
        edges={f"{edge['source']}->{edge['target']}": edge for edge in data["edges"]},
        metrics=data["metrics"],
    )
    session.add(graph)
    await session.flush()
    return graph


def serialize(graph: Graph) -> dict[str, Any]:
    return {
        "id": graph.id,
        "nodes": list((graph.nodes or {}).values()),
        "edges": list((graph.edges or {}).values()),
        "metrics": graph.metrics or {},
    }
