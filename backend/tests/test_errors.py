"""H17: FastAPI's own request-validation errors also use the shared envelope."""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from app.main import create_app


async def test_validation_error_uses_the_error_envelope() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/figures/generate",
            json={"kind": "svg", "description": "x"},
        )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "invalid_request"
    assert body["error"]["message"]
    assert body["error"]["detail"]["errors"]
