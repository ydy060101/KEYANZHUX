"""T5.1: whitelisted discovery, search merge and the import job.

The network is never touched: the source adapters are given canned payloads
and the import job a fake client, so the tests pin parsing, deduplication,
SSRF refusal and the sha256 idempotency (H09/H12) without depending on
arXiv's uptime.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.discover.http import ALLOWED_HOSTS, check_url
from app.discover.sources import (
    Candidate,
    arxiv,
    normalize_title,
    search,
    semantic_scholar,
)
from app.errors import InvalidRequest
from app.models.orm import Document, Job

ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2301.00001v2</id>
    <title>  A   Test Paper  </title>
    <summary>An abstract.</summary>
    <published>2023-01-01T00:00:00Z</published>
    <author><name>Ada Lovelace</name></author>
    <author><name>Alan Turing</name></author>
    <link title="pdf" href="https://arxiv.org/pdf/2301.00001v2"/>
  </entry>
</feed>
"""

S2 = b"""{"data": [
  {"paperId": "abc123", "title": "A Test Paper", "year": 2023,
   "authors": [{"name": "Ada Lovelace"}],
   "abstract": "An abstract.",
   "externalIds": {"ArXiv": "2301.00001", "DOI": "10.1/test"},
   "openAccessPdf": {"url": "https://arxiv.org/pdf/2301.00001"}}
]}"""


class FakeClient:
    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.payloads = payloads
        self.calls: list[str] = []

    async def get(self, url: str, *, source: str, params: dict[str, Any] | None = None) -> bytes:
        self.calls.append(source)
        if source not in self.payloads:
            raise RuntimeError(f"no payload for {source}")
        return self.payloads[source]


def test_whitelist_covers_h09_and_rejects_everything_else() -> None:
    for host in ("arxiv.org", "export.arxiv.org", "api.semanticscholar.org", "api.openalex.org"):
        check_url(f"https://{host}/x")
    assert "api.github.com" in ALLOWED_HOSTS
    with pytest.raises(InvalidRequest):
        check_url("http://169.254.169.254/latest/meta-data")
    with pytest.raises(InvalidRequest):
        check_url("https://evil.example.com/paper.pdf")
    with pytest.raises(InvalidRequest):
        check_url("file:///C:/secret.pdf")


def test_a_pdf_on_a_host_we_cannot_reach_is_not_advertised() -> None:
    from app.discover.http import safe_pdf_url

    assert safe_pdf_url("https://arxiv.org/pdf/1706.03762") == "https://arxiv.org/pdf/1706.03762"
    assert safe_pdf_url("https://doi.org/10.1609/aaai.v34i07.6693") is None
    assert safe_pdf_url(None) is None


async def test_arxiv_atom_is_parsed_without_inventing_fields() -> None:
    client = FakeClient({"arxiv": ATOM})
    found = await arxiv("test paper", client)  # type: ignore[arg-type]
    assert len(found) == 1
    paper = found[0]
    assert paper.ext_id == "2301.00001"
    assert paper.title == "A Test Paper"
    assert paper.authors == ["Ada Lovelace", "Alan Turing"]
    assert paper.year == 2023
    assert paper.pdf_url == "https://arxiv.org/pdf/2301.00001v2"


async def test_semantic_scholar_maps_the_arxiv_id_and_pdf() -> None:
    client = FakeClient({"semanticscholar": S2})
    found = await semantic_scholar("test", client)  # type: ignore[arg-type]
    assert found[0].arxiv_id == "2301.00001"
    assert found[0].doi == "10.1/test"
    assert found[0].pdf_url == "https://arxiv.org/pdf/2301.00001"


async def test_search_merges_duplicates_and_reports_a_failed_source() -> None:
    client = FakeClient({"arxiv": ATOM, "semanticscholar": S2})
    found, statuses = await search("test", client)  # type: ignore[arg-type]
    assert statuses["arxiv"] == "ok"
    assert statuses["semanticscholar"] == "ok"
    assert statuses["openalex"].startswith("error:")
    assert len(found) == 1, "the same paper from two sources is one candidate"
    assert found[0].source == "arxiv", "the arXiv record wins because its PDF is downloadable"


def test_titles_normalize_for_matching() -> None:
    assert normalize_title("Attention Is All You Need!") == "attention is all you need"
    assert normalize_title("BERT: Pre-training") == "bert pre training"


class StubHTTP:
    """Stands in for httpx.AsyncClient inside SafeClient."""

    def __init__(self, status: int, final_url: str | None = None) -> None:
        self.status = status
        self.final_url = final_url
        self.calls = 0

    async def get(self, url: str, params: Any = None) -> Any:
        import httpx

        self.calls += 1
        request = httpx.Request("GET", self.final_url or url)
        return httpx.Response(self.status, request=request, content=b"{}")


async def test_a_404_is_not_retried() -> None:
    from app.discover.http import SafeClient, SourceUnavailable

    safe = SafeClient()
    stub = StubHTTP(404)
    safe._client = stub  # type: ignore[assignment]
    with pytest.raises(SourceUnavailable):
        await safe.get("https://arxiv.org/abs/0000.00000", source="arxiv")
    assert stub.calls == 1, "a wrong id must not be retried three times"


async def test_a_redirect_off_the_whitelist_is_refused() -> None:
    from app.discover.http import SafeClient

    safe = SafeClient()
    safe._client = StubHTTP(200, final_url="http://169.254.169.254/latest/meta-data")  # type: ignore[assignment]
    with pytest.raises(InvalidRequest) as caught:
        await safe.get("https://arxiv.org/abs/2301.00001", source="arxiv")
    assert caught.value.code == "domain_not_allowed"


@pytest.fixture
async def app_client() -> Any:
    from app.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def test_search_endpoint_marks_library_hits(
    session: Any, app_client: AsyncClient, monkeypatch: Any
) -> None:
    import app.api.discover as discover_api

    session.add(
        Document(
            id="doc-known",
            sha256="a" * 64,
            title="A Test Paper",
            status="ready",
            file_path="x.pdf",
        )
    )
    await session.commit()

    async def fake_search(query: str, client: Any, limit: int) -> tuple[list[Candidate], dict[str, str]]:
        return (
            [
                Candidate(source="arxiv", ext_id="2301.00001", title="A Test Paper"),
                Candidate(source="arxiv", ext_id="2302.00002", title="Something Else"),
            ],
            {"arxiv": "ok", "semanticscholar": "error: down"},
        )

    monkeypatch.setattr(discover_api, "search", fake_search)
    response = await app_client.post("/api/v1/discover/search", json={"query": "test"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, list), "the contract answers with ScholarHit[]"
    assert body[0]["in_library"] is True
    assert body[1]["in_library"] is False
    assert body[0]["ext_id"] == "2301.00001"
    assert body[0]["source"] == "arxiv"
    assert "semanticscholar" in response.headers["Warning"], "a partial result says so"


async def test_search_with_every_source_down_is_a_readable_502(
    app_client: AsyncClient, monkeypatch: Any
) -> None:
    import app.api.discover as discover_api

    async def fake_search(query: str, client: Any, limit: int) -> tuple[list[Candidate], dict[str, str]]:
        return [], {"arxiv": "error: timeout", "crossref": "error: 503"}

    monkeypatch.setattr(discover_api, "search", fake_search)
    response = await app_client.post("/api/v1/discover/search", json={"query": "test"})
    assert response.status_code == 502, response.text
    assert response.json()["error"]["code"] == "source_unavailable"


async def test_fetch_creates_an_import_job(
    session: Any, app_client: AsyncClient, monkeypatch: Any
) -> None:
    import app.api.discover as discover_api

    async def fake_enqueue(job_id: str) -> bool:
        return True

    monkeypatch.setattr(discover_api.queue, "enqueue", fake_enqueue)
    response = await app_client.post(
        "/api/v1/discover/fetch", json={"source": "arxiv", "ext_id": "2301.00001"}
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["kind"] == "import" and body["status"] == "queued"
    job = await session.get(Job, body["id"])
    assert job is not None and job.payload["ext_id"] == "2301.00001"

    bad = await app_client.post(
        "/api/v1/discover/fetch", json={"source": "arxiv", "ext_id": "https://evil/x"}
    )
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "invalid_ext_id"


async def test_recommendations_score_by_seed_keyword_overlap(
    session: Any, monkeypatch: Any
) -> None:
    from app.discover import recommend as recommend_module

    session.add_all(
        [
            Document(
                id="seed-1",
                sha256="b" * 64,
                title="Attention Is All You Need",
                status="ready",
                file_path="a.pdf",
                created_by="default",
            ),
            Document(
                id="owned-1",
                sha256="c" * 64,
                title="Attention Is Not All You Need",
                status="ready",
                file_path="b.pdf",
                created_by="default",
                arxiv_id="2201.11111",
            ),
        ]
    )
    await session.commit()

    async def fake_arxiv(query: str, client: Any, limit: int = 10) -> list[Candidate]:
        return [
            Candidate(
                source="arxiv",
                ext_id="2201.11111",
                arxiv_id="2201.11111",
                title="Attention Is Not All You Need",
                year=2022,
            ),
            Candidate(
                source="arxiv",
                ext_id="1706.03762",
                arxiv_id="1706.03762",
                title="Attention Attention Attention",
                year=2017,
            ),
            Candidate(
                source="arxiv",
                ext_id="2305.00003",
                arxiv_id="2305.00003",
                title="Unrelated Diffusion Models",
                year=2023,
            ),
        ]

    monkeypatch.setattr(recommend_module, "arxiv", fake_arxiv)
    rows = await recommend_module.recommend(session, "default", None, 10)  # type: ignore[arg-type]
    assert [row["paper_id"] for row in rows] == ["1706.03762", "2305.00003"]
    top = rows[0]
    assert top["score"] == 0.5, "one of the seed's two keywords is repeated"
    assert top["reasons"][0].startswith("与库内《")
    assert "attention" in top["reasons"][0].lower()
    assert rows[1]["score"] == 0.0
    assert "检索得到" in rows[1]["reasons"][0]
    assert all(row["source"] == "arxiv" for row in rows)


async def test_recommendations_endpoint_is_empty_without_a_library(
    session: Any, app_client: AsyncClient
) -> None:
    response = await app_client.get("/api/v1/recommendations")
    assert response.status_code == 200, response.text
    assert response.json() == []
    bad = await app_client.get("/api/v1/recommendations?limit=0")
    assert bad.status_code == 400


async def test_import_job_is_idempotent_by_bytes(
    session: Any, monkeypatch: Any
) -> None:
    import app.workers.parse_task  # noqa: F401  (registers "parse")
    from app.workers import import_task
    from app.workers.queue import JobService
    from app.workers.registry import get_handler

    class FakeDownloader:
        async def download(self, url: str, *, source: str) -> bytes:
            return b"%PDF-1.4\n% fake pdf for the import test\n"

    monkeypatch.setattr(import_task, "get_client", lambda: FakeDownloader())
    queued: list[str] = []

    async def fake_enqueue(job_id: str) -> bool:
        queued.append(job_id)
        return True

    monkeypatch.setattr(import_task.queue, "enqueue", fake_enqueue)

    async def run_once() -> dict[str, Any]:
        job = await JobService(session).create(
            kind="import", payload={"source": "arxiv", "ext_id": "2301.00001", "user": "default"}, user="default"
        )
        await session.commit()
        handler = get_handler("import")
        assert handler is not None
        return await handler(job.id, job.payload)

    first = await run_once()
    second = await run_once()
    assert first["doc_id"] == second["doc_id"], "the same bytes are one document (H12)"
    assert second["reused"] is True
    docs = (await session.execute(select(Document))).scalars().all()
    assert len(docs) == 1
    assert docs[0].arxiv_id == "2301.00001"
    assert docs[0].title
    assert len(queued) == 2, "each import queues a parse job"

    docs[0].status = "ready"
    await session.commit()
    third = await run_once()
    assert third["doc_id"] == first["doc_id"]
    assert third["parse_job_id"] is None, "a ready document is not parsed again"
    assert len(queued) == 2
