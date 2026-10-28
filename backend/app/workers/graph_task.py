"""The citation-graph job (T6.1/T6.2).

Matching every selected paper's bibliography against the other selected papers
is cheap, but a graph can carry hundreds of reference rows and must not block a
request (H07), so the API only creates this job. The handler persists the
graph and its metrics, and reports the id the UI needs to open it.
"""

from __future__ import annotations

import logging
from typing import Any

from ..db import get_session_factory
from ..graph.service import create_graph, serialize
from .queue import JobService
from .registry import register_handler

logger = logging.getLogger(__name__)


async def graph_job(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    doc_ids = [str(value) for value in payload.get("doc_ids") or []]
    factory = get_session_factory()

    async with factory() as session:
        await JobService(session).progress(job_id, stage="matching references", progress=0.1)
        graph = await create_graph(session, doc_ids)
        await session.commit()
        data = serialize(graph)

    metrics = data["metrics"]
    logger.info(
        "graph job done graph_id=%s nodes=%d edges=%d",
        data["id"],
        metrics["node_count"],
        metrics["edge_count"],
    )
    return {
        "graph_id": data["id"],
        "node_count": metrics["node_count"],
        "edge_count": metrics["edge_count"],
        "isolated": len(metrics["isolated"]),
        "unmatched_references": metrics["unmatched_references"],
    }


register_handler("graph", graph_job)
