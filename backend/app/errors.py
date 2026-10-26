"""Unified error envelope (AGENTS.md H17).

Every API error renders as ``{"error": {"code", "message", "detail"}}``.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Base class for expected, user-facing failures."""

    code: str = "internal_error"
    status_code: int = 500

    def __init__(
        self,
        message: str,
        *,
        detail: dict[str, Any] | None = None,
        code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code

    def to_payload(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "detail": self.detail}}


class NotFound(AppError):
    code = "not_found"
    status_code = 404


class InvalidRequest(AppError):
    code = "invalid_request"
    status_code = 400


class Conflict(AppError):
    code = "conflict"
    status_code = 409


class PayloadTooLarge(AppError):
    code = "payload_too_large"
    status_code = 413


class UnsupportedMedia(AppError):
    code = "unsupported_media_type"
    status_code = 415


class FeatureDisabled(AppError):
    code = "feature_disabled"
    status_code = 400


class ExternalServiceError(AppError):
    code = "external_service_error"
    status_code = 502


class RefusedAnswer(AppError):
    """Raised when no evidence clears the rerank threshold (H03)."""

    code = "refused_no_evidence"
    status_code = 200


async def app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return JSONResponse(status_code=exc.status_code, content=exc.to_payload())


async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "服务器内部错误，请稍后重试",
                "detail": {"type": type(exc).__name__},
            }
        },
    )
