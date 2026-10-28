"""Application entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .errors import (
    AppError,
    app_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
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
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    from .api import data as data_api
    from .api import discover as discover_api
    from .api import documents as documents_api
    from .api import figures as figures_api
    from .api import graphs as graphs_api
    from .api import jobs as jobs_api
    from .api import qa as qa_api
    from .api import translate as translate_api
    from .api import writing as writing_api
    from .workers import register_all

    register_all()
    app.include_router(jobs_api.router, prefix=settings.api_prefix)
    app.include_router(documents_api.router, prefix=settings.api_prefix)
    app.include_router(data_api.router, prefix=settings.api_prefix)
    app.include_router(figures_api.router, prefix=settings.api_prefix)
    app.include_router(qa_api.router, prefix=settings.api_prefix)
    app.include_router(translate_api.router, prefix=settings.api_prefix)
    app.include_router(discover_api.router, prefix=settings.api_prefix)
    app.include_router(graphs_api.router, prefix=settings.api_prefix)
    app.include_router(writing_api.router, prefix=settings.api_prefix)

    _mount_frontend(app)
    return app


def _dist_dir() -> Path:
    """The production frontend built by `npm run build`, if it exists.

    `backend/app/main.py` → repository root is two parents up. Keeping the
    lookup relative to this file means the packaged launcher can run the API
    from any working directory.
    """
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built SPA next to the API (portable launcher, T8.4).

    Development uses Vite's proxy and never reaches these routes. In the
    packaged form the API is the only server, so `/` must return
    `index.html`, hashed assets come from `/assets`, and unknown *page* paths
    fall back to the SPA. `/api/*` is deliberately excluded: an unknown API
    path must stay a 404 JSON response instead of returning HTML to a client
    that will try to parse it.
    """
    dist = _dist_dir()
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        if full_path.startswith("api/") or full_path == "openapi.json":
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = (dist / full_path).resolve()
        if full_path and dist.resolve() in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        index = dist / "index.html"
        if index.is_file():
            return FileResponse(index)
        raise HTTPException(status_code=404, detail="Not Found")


app = create_app()
