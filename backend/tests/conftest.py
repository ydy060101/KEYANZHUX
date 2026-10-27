"""Shared fixtures.

Tests that touch the database need PostgreSQL (the schema uses JSONB, arrays
and pgvector). They are skipped when the server is not reachable so a
lint-only checkout still runs; `tools.ps1 test` starts the server first.

Each test session uses `<configured_db>_test`, created on demand and owned by
the application role, so a run can never touch development data. The superuser
connection is only used to create that database and the `vector` extension;
everything else runs as the application role.
"""

import asyncio
import socket
import sys
from collections.abc import AsyncIterator
from typing import Any

import pytest

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


def _parts(url: str) -> tuple[str, int, str, str]:
    """(host, port, user, dbname) from a SQLAlchemy URL."""
    rest = url.split("://", 1)[-1]
    credentials, _, hostpart = rest.rpartition("@")
    hostport, _, dbname = hostpart.partition("/")
    host, _, port = hostport.partition(":")
    user = credentials.split(":", 1)[0]
    return host, int(port or "5432"), user, dbname.split("?")[0]


@pytest.fixture(scope="session")
def test_database_url() -> str:
    from app.config import get_settings

    url = get_settings().database_url
    host, port, _user, dbname = _parts(url)
    try:
        with socket.create_connection((host, port), timeout=1.0):
            pass
    except OSError:
        pytest.skip(f"PostgreSQL is not running on {host}:{port}")
    return url.rsplit("/", 1)[0] + f"/{dbname}_test"


@pytest.fixture(scope="session", autouse=True)
def _prepare_test_database(test_database_url: str) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app import db
    from app.config import get_settings
    from app.models.orm import Base

    configured = get_settings().database_url
    host, port, user, _dbname = _parts(configured)
    test_name = test_database_url.rsplit("/", 1)[-1]
    admin_url = f"postgresql+psycopg://postgres@{host}:{port}/postgres"

    async def setup() -> None:
        admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        try:
            async with admin.connect() as conn:
                exists = await conn.scalar(
                    text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": test_name}
                )
                if not exists:
                    await conn.execute(text(f'CREATE DATABASE "{test_name}" OWNER "{user}"'))
        finally:
            await admin.dispose()

        superuser = create_async_engine(admin_url.rsplit("/", 1)[0] + f"/{test_name}", isolation_level="AUTOCOMMIT")
        try:
            async with superuser.connect() as conn:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        finally:
            await superuser.dispose()

        db.use_database(test_database_url)
        engine = db.get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(setup())


@pytest.fixture
async def session() -> AsyncIterator[Any]:
    """A session against an empty schema, rebuilt before each test.

    Tables are dropped rather than the schema: the `vector` extension lives in
    `public` and the application role may not recreate it.
    """
    from app.db import get_engine, get_session_factory
    from app.models.orm import Base

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    factory = get_session_factory()
    async with factory() as s:
        yield s


@pytest.fixture(scope="module")
def paper_chunks() -> list[Any]:
    """The Attention-v1 fixture, parsed and chunked once per test module.

    Used by both retrieval test modules; parsing a 15-page paper per test would
    dominate the suite's runtime for no benefit, and the chunks are identical
    every time (H06).
    """
    from pathlib import Path

    from app.ingest.parser import parse_pdf
    from app.rag.chunk import Chunker

    path = Path(__file__).resolve().parent.parent / "fixtures" / "pdf" / "1706.03762v1.pdf"
    if not path.is_file():
        pytest.skip("1706.03762v1.pdf is not staged")
    result = parse_pdf(path, "doc-transformer")
    chunker = Chunker()
    return chunker.feed(result.model.blocks) + chunker.flush()
