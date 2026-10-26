"""Application entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .errors import AppError, app_error_handler, unhandled_error_handler

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format='{"level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
    )
    logger.info("starting api")
    try:
        yield
    finally:
        from .llm.gateway import get_gateway

        try:
            await get_gateway().close()
        except Exception:  # pragma: no cover - shutdown must not raise
            logger.warning("gateway close failed")
        logger.info("stopped api")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="research Agent", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
