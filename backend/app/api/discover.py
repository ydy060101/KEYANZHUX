"""Discovery endpoints (01 §5.4, T5.1/T5.6).

`POST /discover/search` answers with candidates from arXiv, Semantic Scholar,
OpenAlex and Crossref. Each hit carries `in_library` and `ext_id` in addition
to the contract's `ScholarHit` fields (additive; the schema allows it) because
the UI needs to know what it already owns and `POST /discover/fetch` needs the
source-specific id. A source that fails is dropped from the merged result; when
*every* source fails the request answers 502 instead of pretending the library
is empty (H08).

`POST /discover/fetch` creates an `import` job rather than downloading in the
request: a PDF download plus dedup is expected to exceed the 2 s budget (H07),
so it answers 202 with the job row.

`GET /recommendations` builds a feed from the library's own titles (T5.6): each
seed title is searched on arXiv, already-owned papers are removed, and every
row's score is the title-keyword overlap with the seed — a number the reader
can check, not a model's opinion (H02).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..deps import SessionDep, UserIdDep
from ..discover.http import SourceUnavailable, get_client
from ..discover.recommend import recommend
from ..discover.sources import normalize_title, search
from ..errors import InvalidRequest
from ..models.orm import Document
from ..workers import queue
from ..workers.queue import snapshot_of

logger = logging.getLogger(__name__)

router = APIRouter(tags=["discover"])

Source = Literal["arxiv", "semanticscholar", "openalex", "crossref"]

# arXiv ids, DOIs, Semantic Scholar hashes and OpenAlex work ids all fit this;
# the check exists to keep a URL or a control character out of the lookup.
_EXT_ID = re.compile(r"^[A-Za-z0-9._:/()\-]{1,200}$")


class SearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    limit: int = Field(default=10, ge=1, le=50)


class FetchBody(BaseModel):
    source: Source
    ext_id: str = Field(min_length=1, max_length=200)


@router.post("/discover/search")
async def discover_search(
    body: SearchBody, session: SessionDep, user: UserIdDep, response: Response
) -> list[dict[str, Any]]:
    query = body.query.strip()
    if not query:
        raise InvalidRequest("搜索词不能为空")
    candidates, statuses = await search(query, get_client(), body.limit)
    if all(status != "ok" for status in statuses.values()):
        first = next(iter(statuses.values()), "unknown")
        raise SourceUnavailable("discover", first.removeprefix("error: "))

    # The contract's answer is a bare array, so a per-source failure cannot be
    # a body field. A standard `Warning` header tells the client the result is
    # partial without inventing a new response shape (H08).
    failed = sorted(name for name, status in statuses.items() if status != "ok")
    if failed:
        response.headers["Warning"] = f'199 research-agent "{" ".join(failed)} unavailable"'

    rows = (
        await session.execute(
            select(Document.arxiv_id, Document.title).where(Document.created_by == user)
        )
    ).all()
    library_arxiv = {row.arxiv_id for row in rows if row.arxiv_id}
    library_titles = {normalize_title(row.title or "") for row in rows}
    for candidate in candidates:
        candidate.in_library = bool(
            (candidate.arxiv_id and candidate.arxiv_id in library_arxiv)
            or normalize_title(candidate.title) in library_titles
        )
    return [candidate.as_dict() for candidate in candidates]


@router.post("/discover/fetch", status_code=202)
async def discover_fetch(
    body: FetchBody, session: SessionDep, user: UserIdDep, response: Response
) -> dict[str, Any]:
    ext_id = body.ext_id.strip()
    # A DOI contains one `/`, so the character class allows it; a URL or a
    # path traversal does not belong in an identifier and is refused here
    # rather than being pasted into a provider URL.
    if not _EXT_ID.match(ext_id) or "://" in ext_id or ext_id.startswith("/") or ".." in ext_id:
        raise InvalidRequest("文献标识不合法", code="invalid_ext_id")
    job = await queue.JobService(session).create(
        kind="import",
        payload={"source": body.source, "ext_id": ext_id, "user": user},
        user=user,
    )
    await session.commit()
    if not await queue.enqueue(job.id):
        asyncio.create_task(queue.run_in_background(job.id))
    response.headers["Location"] = f"/api/v1/jobs/{job.id}"
    return snapshot_of(job)


@router.get("/recommendations")
async def recommendations(
    session: SessionDep, user: UserIdDep, limit: int = 20
) -> list[dict[str, Any]]:
    if limit < 1 or limit > 50:
        raise InvalidRequest("limit 必须在 1 到 50 之间", code="invalid_limit")
    return await recommend(session, user, get_client(), limit)
