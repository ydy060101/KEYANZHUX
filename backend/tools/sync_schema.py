"""Bring the database schema up to the models, without touching stored data.

The project has no migration tool yet (it is on the pending list), so the
schema is `Base.metadata.create_all`. That creates missing tables but never
alters an existing one, which is exactly the gap this script fills for the two
changes T2.5 makes:

  * `section_summaries` is a new table — created here;
  * `chunks.tsv` changed from a plain text column to a generated tsvector.

Rebuilding `chunks` is only safe while it is empty, which it is: nothing wrote
chunks before T2.5 (the table existed but no code path inserted into it). The
script refuses to drop it once it holds rows, and says what to do instead.

Run from `backend/`:

    .venv/Scripts/python.exe -I tools/sync_schema.py [--dry-run]
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from sqlalchemy import inspect, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncEngine  # noqa: E402

from app import db  # noqa: E402
from app.models.orm import Base  # noqa: E402

# Tables whose columns changed shape and that are safe to rebuild only when
# empty. Each entry says why it is expected to be empty.
REBUILDABLE = {
    "chunks": "written for the first time in T2.5",
}

# Columns added after a table was created. `create_all` never alters an
# existing table, so an additive column needs an explicit ALTER.
ADDED_COLUMNS = {
    "documents": {
        "meta": "jsonb NOT NULL DEFAULT '{}'::jsonb",
    },
    "assets": {
        "html": "text",
    },
    "section_summaries": {
        "level": "integer NOT NULL DEFAULT 1",
    },
}

# Indexes added after a table was created. `create_all` builds a table's
# indexes only when it creates the table, so an existing `chunks` table needs
# them explicitly (T3.1). `IF NOT EXISTS` makes the script re-runnable.
ADDED_INDEXES = [
    (
        "ix_chunks_embedding_hnsw",
        "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw "
        "ON chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)",
    ),
    ("ix_chunks_tsv", "CREATE INDEX IF NOT EXISTS ix_chunks_tsv ON chunks USING gin (tsv)"),
]


async def main(dry_run: bool) -> int:
    engine = db.get_engine()
    async with engine.connect() as conn:
        existing = set(await conn.run_sync(lambda sync: inspect(sync).get_table_names()))

    missing = [name for name in Base.metadata.tables if name not in existing]
    rebuild: list[str] = []
    for name in REBUILDABLE:
        if name not in existing:
            continue
        if not await _needs_rebuild(engine, name):
            continue
        async with engine.connect() as conn:
            rows = await conn.scalar(text(f'SELECT count(*) FROM "{name}"'))
        if rows:
            print(f"refusing to rebuild {name}: it holds {rows} rows")
            return 1
        rebuild.append(name)

    print(f"missing tables: {missing or 'none'}")
    print(f"tables to rebuild: {rebuild or 'none'}")
    added = await _missing_columns(engine)
    print(f"columns to add: {added or 'none'}")
    if dry_run:
        print("dry run: nothing changed")
        await engine.dispose()
        return 0

    for name in rebuild:
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    for table, column, ddl in added:
        async with engine.begin() as conn:
            await conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {ddl}'))
    for name, ddl in ADDED_INDEXES:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(ddl))
        except Exception as exc:  # pragma: no cover - needs an older pgvector
            # An HNSW index needs pgvector >= 0.5. Saying so beats a stack
            # trace: the app still works without it, just with a sequential
            # scan over the vectors.
            print(f"index {name} not created ({type(exc).__name__}): {exc}")

    async with engine.connect() as conn:
        after = set(await conn.run_sync(lambda sync: inspect(sync).get_table_names()))
    print(f"schema now has {len(after)} tables")
    await engine.dispose()
    return 0


async def _needs_rebuild(engine: AsyncEngine, table: str) -> bool:
    """Whether a stored table still has a shape the models no longer describe.

    Rebuilding is destructive, so it happens only when the table really
    differs from the model — otherwise every run after the first would refuse
    to do anything once the rebuilt table had been filled with real rows.
    """
    async with engine.connect() as conn:
        stored = await conn.run_sync(_columns_of(table))
    declared = {column.name for column in Base.metadata.tables[table].columns}
    return stored != declared


def _columns_of(table: str) -> Callable[[Any], set[str]]:
    def read(sync: Any) -> set[str]:
        return {str(col["name"]) for col in inspect(sync).get_columns(table)}

    return read


async def _missing_columns(engine: AsyncEngine) -> list[tuple[str, str, str]]:
    """Declared columns that an existing table does not have yet."""
    out: list[tuple[str, str, str]] = []
    for table, columns in ADDED_COLUMNS.items():
        async with engine.connect() as conn:
            present = await conn.run_sync(_columns_of(table))
        if not present:
            continue  # the table itself is missing; create_all will build it whole
        for column, ddl in columns.items():
            if column not in present:
                out.append((table, column, ddl))
    return out


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main("--dry-run" in sys.argv)))
