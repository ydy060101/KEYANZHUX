"""arq worker entry point.

`tools.ps1 dev` starts this alongside uvicorn. The worker shares the app's
database and Redis configuration; job state always lives in the `jobs` table,
so the API keeps working if the worker is down (H08).

The worker builds its own event loop, so on Windows the selector policy must be
set before arq creates it (psycopg cannot run on ProactorEventLoop).
"""

from __future__ import annotations

import asyncio
import sys

from arq.connections import RedisSettings
from arq.worker import create_worker

from .config import get_settings
from .logging_setup import configure_logging

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import logging  # noqa: E402
from typing import Any  # noqa: E402

from .workers import queue  # noqa: E402

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


def main() -> None:
    configure_logging(get_settings().log_level)
    worker = create_worker(WorkerSettings)  # type: ignore[arg-type]  # arq accepts the class
    worker.run()


if __name__ == "__main__":
    main()
