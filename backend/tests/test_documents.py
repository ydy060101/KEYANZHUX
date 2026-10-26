"""T1.2 acceptance: upload, idempotency, CRUD, Range streaming, cleanup."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.ingest import storage
from app.main import create_app

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "pdf" / "1706.03762v1.pdf"


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path: Path, monkeypatch: Any) -> AsyncIterator[None]:
    """Keep uploaded bytes out of the real data directory."""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    yield


@pytest.fixture
async def client(session: Any) -> AsyncIterator[AsyncClient]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _pdf(name: str = "1706.03762v1.pdf") -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("files", (name, FIXTURE.read_bytes(), "application/pdf"))]


async def test_upload_creates_document_and_job(client: AsyncClient, session: Any) -> None:
    response = await client.post("/api/v1/documents", files=_pdf())
    assert response.status_code == 202, response.text
    body = response.json()
    assert len(body) == 1
    item = body[0]
    assert item["doc_id"]
    assert item["job_id"]
    assert item["dedup"] is None

    detail = await client.get(f"/api/v1/documents/{item['doc_id']}")
    assert detail.status_code == 200
    assert detail.json()["title"] == "Attention Is All You Need"
    assert detail.json()["arxiv_id"] == "1706.03762"
    assert detail.json()["version"] == "v1"


async def test_reupload_same_bytes_is_idempotent(client: AsyncClient, session: Any) -> None:
    first = (await client.post("/api/v1/documents", files=_pdf())).json()[0]
    second = (await client.post("/api/v1/documents", files=_pdf("renamed.pdf"))).json()[0]
    assert first["doc_id"] == second["doc_id"], "the same bytes must map to one document"

    listing = (await client.get("/api/v1/documents")).json()
    assert listing["total"] == 1


async def test_upload_rejects_non_pdf(client: AsyncClient, session: Any) -> None:
    response = await client.post(
        "/api/v1/documents", files=[("files", ("x.pdf", b"not a pdf at all" * 100, "application/pdf"))]
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"


async def test_upload_rejects_wrong_extension(client: AsyncClient, session: Any) -> None:
    response = await client.post(
        "/api/v1/documents", files=[("files", ("x.txt", FIXTURE.read_bytes(), "text/plain"))]
    )
    assert response.status_code == 415


async def test_patch_renames_and_tags(client: AsyncClient, session: Any) -> None:
    doc_id = (await client.post("/api/v1/documents", files=_pdf())).json()[0]["doc_id"]
    response = await client.patch(
        f"/api/v1/documents/{doc_id}", json={"title": "Transformer", "tags": ["nlp", "  ", "arch"]}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Transformer"
    assert body["tags"] == ["nlp", "arch"]


async def test_delete_removes_rows_and_files(client: AsyncClient, session: Any) -> None:
    doc_id = (await client.post("/api/v1/documents", files=_pdf())).json()[0]["doc_id"]
    stored = list(storage.pdf_dir().glob("*.pdf"))
    assert stored, "upload should have written the PDF"

    response = await client.delete(f"/api/v1/documents/{doc_id}")
    assert response.status_code == 204
    assert (await client.get(f"/api/v1/documents/{doc_id}")).status_code == 404
    assert not stored[0].exists()


async def test_missing_document_uses_error_envelope(client: AsyncClient, session: Any) -> None:
    response = await client.get("/api/v1/documents/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_file_stream_full_and_ranged(client: AsyncClient, session: Any) -> None:
    doc_id = (await client.post("/api/v1/documents", files=_pdf())).json()[0]["doc_id"]
    size = FIXTURE.stat().st_size

    full = await client.get(f"/api/v1/documents/{doc_id}/file")
    assert full.status_code == 200
    assert full.headers["accept-ranges"] == "bytes"
    assert len(full.content) == size
    assert full.content[:5] == b"%PDF-"

    partial = await client.get(f"/api/v1/documents/{doc_id}/file", headers={"Range": "bytes=0-99"})
    assert partial.status_code == 206
    assert partial.headers["content-range"] == f"bytes 0-99/{size}"
    assert len(partial.content) == 100

    tail = await client.get(
        f"/api/v1/documents/{doc_id}/file", headers={"Range": f"bytes={size - 10}-"}
    )
    assert tail.status_code == 206
    assert len(tail.content) == 10


async def test_file_range_out_of_bounds(client: AsyncClient, session: Any) -> None:
    doc_id = (await client.post("/api/v1/documents", files=_pdf())).json()[0]["doc_id"]
    response = await client.get(
        f"/api/v1/documents/{doc_id}/file", headers={"Range": "bytes=999999999-"}
    )
    assert response.status_code == 416


async def test_list_filters_by_query_and_status(client: AsyncClient, session: Any) -> None:
    await client.post("/api/v1/documents", files=_pdf())
    assert (await client.get("/api/v1/documents?query=Attention")).json()["total"] == 1
    assert (await client.get("/api/v1/documents?query=nothing-here")).json()["total"] == 0
    assert (await client.get("/api/v1/documents?status=uploading")).json()["total"] == 1
    assert (await client.get("/api/v1/documents?status=ready")).json()["total"] == 0


async def test_list_filters_by_tag(client: AsyncClient, session: Any) -> None:
    doc_id = (await client.post("/api/v1/documents", files=_pdf())).json()[0]["doc_id"]
    await client.patch(f"/api/v1/documents/{doc_id}", json={"tags": ["nlp", "arch"]})
    assert (await client.get("/api/v1/documents?tag=nlp")).json()["total"] == 1
    assert (await client.get("/api/v1/documents?tag=vision")).json()["total"] == 0


V7 = FIXTURE.parent / "1706.03762v7.pdf"
V1 = FIXTURE


def _pdf_at(path: Path, name: str) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("files", (name, path.read_bytes(), "application/pdf"))]


async def test_case_3_1_v7_then_v1_through_upload(client: AsyncClient, session: Any) -> None:
    """04 §1 case 3.1 at the API boundary: v7 first, v1 second."""
    first = (await client.post("/api/v1/documents", files=_pdf_at(V7, "1706.03762v7.pdf"))).json()[0]
    assert first["dedup"] is None

    second = (await client.post("/api/v1/documents", files=_pdf_at(V1, "1706.03762v1.pdf"))).json()[0]
    dedup = second["dedup"]
    assert dedup is not None, "the second upload must be flagged"
    assert dedup["level"] == "same_paper_other_version"
    assert dedup["matched_doc_id"] == first["doc_id"]
    assert dedup["existing_version"] == "v7"
    assert dedup["new_version"] == "v1"
    assert dedup["suggestion"] == "keep_existing"
    assert "较新" in dedup["reason"]


async def test_case_3_1_rename_keeps_verdict(client: AsyncClient, session: Any) -> None:
    await client.post("/api/v1/documents", files=_pdf_at(V7, "1706.03762v7.pdf"))
    second = (
        await client.post("/api/v1/documents", files=_pdf_at(V1, "completely_different_name.pdf"))
    ).json()[0]
    assert second["dedup"]["level"] == "same_paper_other_version"


async def test_resolve_keep_existing_removes_new_upload(client: AsyncClient, session: Any) -> None:
    first = (await client.post("/api/v1/documents", files=_pdf_at(V7, "1706.03762v7.pdf"))).json()[0]
    second = (await client.post("/api/v1/documents", files=_pdf_at(V1, "1706.03762v1.pdf"))).json()[0]

    response = await client.post(
        f"/api/v1/documents/{second['doc_id']}/dedup/resolve",
        json={"action": "keep_existing", "target_id": first["doc_id"]},
    )
    assert response.status_code == 200
    assert response.json()["id"] == first["doc_id"]
    assert (await client.get(f"/api/v1/documents/{second['doc_id']}")).status_code == 404
    assert (await client.get(f"/api/v1/documents/{first['doc_id']}")).status_code == 200


async def test_resolve_keep_both_keeps_two(client: AsyncClient, session: Any) -> None:
    first = (await client.post("/api/v1/documents", files=_pdf_at(V7, "1706.03762v7.pdf"))).json()[0]
    second = (await client.post("/api/v1/documents", files=_pdf_at(V1, "1706.03762v1.pdf"))).json()[0]

    response = await client.post(
        f"/api/v1/documents/{second['doc_id']}/dedup/resolve",
        json={"action": "keep_both", "target_id": first["doc_id"]},
    )
    assert response.status_code == 200
    assert (await client.get("/api/v1/documents")).json()["total"] == 2


async def test_resolve_replace_removes_library_copy(client: AsyncClient, session: Any) -> None:
    first = (await client.post("/api/v1/documents", files=_pdf_at(V7, "1706.03762v7.pdf"))).json()[0]
    second = (await client.post("/api/v1/documents", files=_pdf_at(V1, "1706.03762v1.pdf"))).json()[0]

    response = await client.post(
        f"/api/v1/documents/{second['doc_id']}/dedup/resolve",
        json={"action": "replace", "target_id": first["doc_id"]},
    )
    assert response.status_code == 200
    assert response.json()["id"] == second["doc_id"]
    assert (await client.get(f"/api/v1/documents/{first['doc_id']}")).status_code == 404


async def test_resolve_rejects_unknown_action(client: AsyncClient, session: Any) -> None:
    doc_id = (await client.post("/api/v1/documents", files=_pdf())).json()[0]["doc_id"]
    response = await client.post(
        f"/api/v1/documents/{doc_id}/dedup/resolve", json={"action": "delete_everything"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


async def test_version_diff_of_unparsed_docs_is_not_reported_as_unchanged(
    client: AsyncClient, session: Any
) -> None:
    """CR-003: no parsed sections means "cannot compare", never "no changes"."""
    first = (await client.post("/api/v1/documents", files=_pdf_at(V7, "1706.03762v7.pdf"))).json()[0]
    second = (await client.post("/api/v1/documents", files=_pdf_at(V1, "1706.03762v1.pdf"))).json()[0]

    response = await client.get(
        f"/api/v1/documents/{second['doc_id']}/versions/diff",
        params={"other": first["doc_id"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["comparable"] is False
    assert "尚未解析" in body["summary"]
    assert "无任何变化" not in body["summary"]
    assert body["sections"] == []
