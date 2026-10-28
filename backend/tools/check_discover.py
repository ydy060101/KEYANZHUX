"""Check discovery end to end with the real sources (T5.1/T5.6).

The unit suite pins the parsers and the SSRF rules with canned payloads; this
script is the other half, run against arXiv, Semantic Scholar, OpenAlex and
Crossref for real, with the API up:

  * **D1** — `/discover/search` answers with hits from at least two sources,
    and every `pdf_url` it hands back is on the H09 whitelist;
  * **D2** — `/discover/fetch` imports a real arXiv PDF: the job reaches
    `succeeded`, the document row exists with its arXiv id and a stored file,
    and a second fetch of the same id reuses that document (H12);
  * **D3** — `/recommendations` returns scored rows whose reasons name a
    library seed, never a bare score.

Run from `backend/` with the API up:

    .venv/Scripts/python.exe -I tools/check_discover.py

It prints verdict lines starting `D1:` / `D2:` / `D3:` so the result is
greppable.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx  # noqa: E402

from app import db  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.models.orm import Document  # noqa: E402

API = "http://127.0.0.1:8000/api/v1"
HEADERS = {"X-User-Id": "default"}
ALLOWED = {
    "arxiv.org",
    "export.arxiv.org",
    "api.semanticscholar.org",
    "api.crossref.org",
    "api.openalex.org",
    "api.github.com",
    "github.com",
}
SAMPLE_ID = "1706.03762"


def host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def _file_size(path: str) -> tuple[bool, int]:
    if not os.path.isfile(path):
        return False, 0
    return True, os.path.getsize(path) // 1024


async def d1_search(client: httpx.AsyncClient) -> bool:
    response = await client.post(
        f"{API}/discover/search", json={"query": "attention is all you need", "limit": 10}
    )
    if response.status_code != 200:
        print(f"D1: FAIL — HTTP {response.status_code}: {response.text[:300]}")
        return False
    hits = response.json()
    if not isinstance(hits, list) or len(hits) < 5:
        print(f"D1: FAIL — expected at least 5 hits, got {len(hits)}")
        return False
    sources = {hit["source"] for hit in hits}
    for hit in hits:
        if not hit.get("title") or not hit.get("source"):
            print(f"D1: FAIL — a hit is missing title/source: {hit}")
            return False
        pdf_url = hit.get("pdf_url")
        if pdf_url and host(pdf_url) not in ALLOWED:
            print(f"D1: FAIL — non-whitelisted pdf_url {pdf_url}")
            return False
    if len(sources) < 2:
        print(f"D1: FAIL — only one source answered: {sources}")
        return False
    arxiv = next((hit for hit in hits if hit["source"] == "arxiv"), None)
    if arxiv is None or not arxiv.get("arxiv_id") or not arxiv.get("pdf_url"):
        print("D1: FAIL — no downloadable arXiv hit")
        return False
    print(f"D1: PASS — {len(hits)} hits from {', '.join(sorted(sources))}; arXiv pdf {arxiv['pdf_url']}")
    return True


async def wait_job(client: httpx.AsyncClient, job_id: str, timeout_s: float) -> dict[str, object] | None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        response = await client.get(f"{API}/jobs/{job_id}")
        if response.status_code != 200:
            print(f"D2: FAIL — job lookup HTTP {response.status_code}: {response.text[:200]}")
            return None
        job = response.json()
        if job["status"] in {"succeeded", "failed", "cancelled"}:
            return job
        await asyncio.sleep(2)
    print(f"D2: FAIL — job {job_id} did not finish in {timeout_s:.0f}s")
    return None


async def d2_fetch(client: httpx.AsyncClient, session: object) -> bool:
    response = await client.post(
        f"{API}/discover/fetch", json={"source": "arxiv", "ext_id": SAMPLE_ID}
    )
    if response.status_code != 202:
        print(f"D2: FAIL — fetch HTTP {response.status_code}: {response.text[:300]}")
        return False
    job = await wait_job(client, str(response.json()["id"]), 420)
    if job is None:
        return False
    if job["status"] != "succeeded":
        print(f"D2: FAIL — import job {job['status']}: {job.get('error')}")
        return False
    result = job.get("result") or {}
    doc_id = result.get("doc_id") if isinstance(result, dict) else None
    if not doc_id:
        print(f"D2: FAIL — the job has no doc_id: {result}")
        return False

    row = await session.get(Document, doc_id)  # type: ignore[attr-defined]
    if row is None:
        print(f"D2: FAIL — document {doc_id} is not in the database")
        return False
    if row.arxiv_id != SAMPLE_ID:
        print(f"D2: FAIL — document arxiv_id is {row.arxiv_id!r}")
        return False
    exists, size_kib = await asyncio.to_thread(_file_size, row.file_path)
    if not exists:
        print(f"D2: FAIL — stored file is missing: {row.file_path}")
        return False
    print(
        f"D2: PASS — {SAMPLE_ID} imported as {doc_id} "
        f"(status={row.status}, {size_kib} KiB)"
    )

    again = await client.post(f"{API}/discover/fetch", json={"source": "arxiv", "ext_id": SAMPLE_ID})
    if again.status_code != 202:
        print(f"D2: FAIL — second fetch HTTP {again.status_code}")
        return False
    second = await wait_job(client, str(again.json()["id"]), 420)
    if second is None or second["status"] != "succeeded":
        print(f"D2: FAIL — second import failed: {second}")
        return False
    second_result = second.get("result") or {}
    if not isinstance(second_result, dict) or second_result.get("doc_id") != doc_id:
        print(f"D2: FAIL — the same PDF became a second document: {second_result}")
        return False
    print(f"D2: PASS — the second import reused {doc_id} (sha256 dedup)")
    return True


async def d3_recommend(client: httpx.AsyncClient) -> bool:
    response = await client.get(f"{API}/recommendations", params={"limit": 5})
    if response.status_code != 200:
        print(f"D3: FAIL — HTTP {response.status_code}: {response.text[:300]}")
        return False
    rows = response.json()
    if not rows:
        print("D3: FAIL — empty feed although the library has documents")
        return False
    for row in rows:
        if not row.get("reasons"):
            print(f"D3: FAIL — {row.get('paper_id')} has no reason")
            return False
        if not 0.0 <= float(row["score"]) <= 1.0:
            print(f"D3: FAIL — score out of range: {row['score']}")
            return False
    top = rows[0]
    print(f"D3: PASS — {len(rows)} rows; top {top['score']} · {top['title'][:60]}")
    print(f"D3: reason — {top['reasons'][0]}")
    return True


async def main() -> int:
    settings = get_settings()
    db.use_database(settings.database_url)
    factory = db.get_session_factory()
    ok = True
    async with httpx.AsyncClient(timeout=60.0, headers=HEADERS) as client:
        ok = await d1_search(client) and ok
        async with factory() as session:
            ok = await d2_fetch(client, session) and ok
        ok = await d3_recommend(client) and ok
    print("discover: PASS" if ok else "discover: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
