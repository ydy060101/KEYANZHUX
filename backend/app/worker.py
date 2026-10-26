"""arq worker entry point.

`tools.ps1 dev` starts this alongside uvicorn. The worker shares the app's
database and Redis configuration; job state always lives in the `jobs` table,
so the API keeps working if the worker is down (H08).
"""

from __future__ import annotations

import logging
from typing import Any

from arq.connections import RedisSettings

from .config import get_settings
from .logging_setup import configure_logging
from .workers import queue

logger = logging.getLogger(__name__)


async def run_job(ctx: dict[str, Any], job_id: str) -> None:
    await queue.execute(job_id)


async def startup(ctx: dict[str, Any]) -> None:
    from .workers import register_all

    register_all()
    logger.info("worker started")


async def shutdown(ctx: dict[str, Any]) -> None:
    logger.info("worker stopped")


class WorkerSettings:
    """Read by `arq app.worker.WorkerSettings`."""

    functions = [run_job]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_tries = 3
    job_timeout = 900
    keep_result = 3600
    retry_jobs = False  # retries are explicit user actions (T1.1)

    @staticmethod
    def configure() -> None:
        configure_logging(get_settings().log_level)
