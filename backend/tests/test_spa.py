"""Serving the built SPA from the API (portable launcher, T8.4).

The launcher opens `http://127.0.0.1:8000/`, so the API must answer page paths
with `frontend/dist/index.html` while keeping unknown `/api/*` paths JSON 404s.
The test is skipped when the frontend has not been built, as in a backend-only
checkout.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@pytest.fixture
async def app_client() -> AsyncIterator[AsyncClient]:
    from app.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.mark.skipif(not (DIST / "index.html").is_file(), reason="frontend not built")
async def test_page_paths_return_the_spa(app_client: AsyncClient) -> None:
    for path in ("/", "/reader/doc-1", "/discover"):
        response = await app_client.get(path)
        assert response.status_code == 200, (path, response.text[:200])
        assert "text/html" in response.headers["content-type"]
        assert "<div id=\"root\">" in response.text


async def test_unknown_api_path_stays_a_json_404(app_client: AsyncClient) -> None:
    response = await app_client.get("/api/v1/definitely-not-a-route")
    assert response.status_code == 404
    assert "application/json" in response.headers["content-type"]
    assert response.json() == {"detail": "Not Found"}


@pytest.mark.skipif(not (DIST / "index.html").is_file(), reason="frontend not built")
async def test_openapi_is_not_shadowed(app_client: AsyncClient) -> None:
    response = await app_client.get("/openapi.json")
    assert response.status_code == 200
    assert "application/json" in response.headers["content-type"]
    payload: Any = response.json()
    assert "/api/v1/qa" in payload["paths"]
