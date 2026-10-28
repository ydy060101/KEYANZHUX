"""Application entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .errors import AppError, app_error_handler, unhandled_error_handler
from .logging_setup import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
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

    from .api import discover as discover_api
    from .api import documents as documents_api
    from .api import graphs as graphs_api
    from .api import jobs as jobs_api
    from .api import qa as qa_api
    from .api import translate as translate_api
    from .api import writing as writing_api
    from .workers import register_all

    register_all()
    app.include_router(jobs_api.router, prefix=settings.api_prefix)
    app.include_router(documents_api.router, prefix=settings.api_prefix)
    app.include_router(qa_api.router, prefix=settings.api_prefix)
    app.include_router(translate_api.router, prefix=settings.api_prefix)
    app.include_router(discover_api.router, prefix=settings.api_prefix)
    app.include_router(graphs_api.router, prefix=settings.api_prefix)
    app.include_router(writing_api.router, prefix=settings.api_prefix)

    return app


app = create_app()
