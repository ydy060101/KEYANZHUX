"""Citation-graph endpoints (01 §5.5, T6.1/T6.2).

`POST /graphs` accepts the selected documents and answers with the `Job` that
builds the graph; `GET /graphs/{id}` serves the stored graph with roles and
metrics. The graph of an earlier run is immutable, so a client that reloads the
page gets exactly what the job produced.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from ..deps import SessionDep, UserIdDep
from ..errors import Conflict, InvalidRequest, NotFound
from ..graph.service import MAX_DOCS, serialize
from ..models.orm import Document
from ..models.orm import Graph as GraphRow
from ..workers import queue
from ..workers.queue import snapshot_of

router = APIRouter(tags=["graphs"])


class GraphBody(BaseModel):
    doc_ids: list[str]


@router.post("/graphs", status_code=202)
async def build_graph(body: GraphBody, session: SessionDep, user: UserIdDep) -> dict[str, Any]:
    doc_ids = list(dict.fromkeys(body.doc_ids))
    if len(doc_ids) < 2:
        raise InvalidRequest("至少选择两篇不同的文献才能构建引用图", detail={"doc_ids": body.doc_ids})
    if len(doc_ids) > MAX_DOCS:
        raise InvalidRequest(f"一次最多构建 {MAX_DOCS} 篇文献的引用图", detail={"selected": len(doc_ids)})

    rows = (await session.execute(select(Document.id, Document.status).where(Document.id.in_(doc_ids)))).all()
    found = {row.id: row.status for row in rows}
    missing = [doc_id for doc_id in doc_ids if doc_id not in found]
    if missing:
        raise NotFound("部分文献不存在", detail={"doc_ids": missing})
    not_ready = [doc_id for doc_id in doc_ids if found[doc_id] != "ready"]
    if not_ready:
        raise Conflict("文献尚未解析完成，无法构建引用图", detail={"doc_ids": not_ready})

    job = await queue.JobService(session).create(kind="graph", payload={"doc_ids": doc_ids}, user=user)
    await session.commit()
    if not await queue.enqueue(job.id):
        asyncio.create_task(queue.run_in_background(job.id))
    return snapshot_of(job)


@router.get("/graphs/{graph_id}")
async def get_graph(graph_id: str, session: SessionDep) -> dict[str, Any]:
    graph = await session.get(GraphRow, graph_id)
    if graph is None:
        raise NotFound("图谱不存在", detail={"graph_id": graph_id})
    return serialize(graph)
