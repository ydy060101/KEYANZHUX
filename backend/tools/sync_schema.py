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
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from sqlalchemy import inspect, text  # noqa: E402

from app import db  # noqa: E402
from app.models.orm import Base  # noqa: E402

# Tables whose columns changed shape and that are safe to rebuild only when
# empty. Each entry says why it is expected to be empty.
REBUILDABLE = {
    "chunks": "written for the first time in T2.5",
}


async def main(dry_run: bool) -> int:
    engine = db.get_engine()
    async with engine.connect() as conn:
        existing = set(await conn.run_sync(lambda sync: inspect(sync).get_table_names()))

    missing = [name for name in Base.metadata.tables if name not in existing]
    rebuild: list[str] = []
    for name in REBUILDABLE:
        if name in existing:
            async with engine.connect() as conn:
                rows = await conn.scalar(text(f'SELECT count(*) FROM "{name}"'))
            if rows:
                print(f"refusing to rebuild {name}: it holds {rows} rows")
                return 1
            rebuild.append(name)

    print(f"missing tables: {missing or 'none'}")
    print(f"tables to rebuild: {rebuild or 'none'}")
    if dry_run:
        print("dry run: nothing changed")
        await engine.dispose()
        return 0

    for name in rebuild:
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with engine.connect() as conn:
        after = set(await conn.run_sync(lambda sync: inspect(sync).get_table_names()))
    print(f"schema now has {len(after)} tables")
    await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main("--dry-run" in sys.argv)))
