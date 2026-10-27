"""Check hybrid retrieval end to end on the real models (T3.2, acceptance R1).

The unit suite (`tests/test_retrieval.py`) proves the pipeline's mechanics with
a deterministic stub. This script is the other half: it loads the real bge-m3
and bge-reranker-v2-m3, indexes a fixture paper through the same code path the
parse job uses, and measures what the card asks for on a small golden set:

  * **recall@8** — for each hand-checked question, is the chunk holding the
    answer among the eight the pipeline returns?
  * **chunk→block mapping** — every returned hit must name its block ids and
    pages, and those blocks must exist in the document.
  * **scope filtering** — a `doc` scope must not return another document's
    chunk.

The golden set is the one in `tests/test_retrieval.py`, with expectations read
out of the fixture's own text; nothing here is tuned to make the number look
good, and the script prints each miss rather than only the total.

Run from `backend/`:

    .venv/Scripts/python.exe -I tools/check_retrieval.py

It prints a verdict line starting `R1:` so the result is greppable.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

# Chunk text contains symbols a Windows console encodes as GBK.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import func, select, text  # noqa: E402

from app import db  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.ingest.parser import parse_pdf  # noqa: E402
from app.models.orm import Base, Block, Chunk, Document  # noqa: E402
from app.rag.chunk import Chunker  # noqa: E402
from app.rag.embed_pass import embed_document  # noqa: E402
from app.rag.embedding import Embedder  # noqa: E402
from app.rag.index import write_index  # noqa: E402
from app.rag.retrieve import Hit, Scope, retrieve  # noqa: E402
from app.workers.persist import persist_parse  # noqa: E402

PDF = BACKEND / "fixtures" / "pdf" / "1706.03762v1.pdf"
DOC_ID = "check-retrieval"
MIN_RECALL = 0.75

# (question, needle quoted from the paper's text)
GOLDEN: list[tuple[str, str]] = [
    ("How many warmup steps does the learning rate schedule use?", "warmup_steps = 4000"),
    ("What optimizer and beta values were used for training?", "β2 = 0.98"),
    ("How many attention heads does the base model use?", "h = 8"),
    ("What dropout rate was used for the base model?", "Pdrop = 0.1"),
    ("How many identical layers are in the encoder?", "stack of N = 6 identical layers"),
    ("What is the dimension of the model embeddings?", "dmodel = 512"),
    ("How is positional information injected into the model?", "positional encodings"),
    ("What BLEU score did the big model reach on English-to-French?", "41.0"),
]


async def _prepare(session: object) -> None:
    """Parse, chunk and store one paper the way the parse job does.

    Blocks are persisted as well as chunks: the mapping check below asks
    whether every hit's `block_ids` resolve to real `blocks` rows, and a script
    that only wrote chunks would report 0/8 for a pipeline that is correct.
    """
    model = parse_pdf(PDF, DOC_ID).model
    session.add(  # type: ignore[attr-defined]
        Document(
            id=DOC_ID,
            sha256="e" * 64,
            title="Attention Is All You Need",
            status="ready",
            page_count=model.page_count,
            file_path=str(PDF),
        )
    )
    await session.flush()  # type: ignore[attr-defined]
    await persist_parse(session, model)  # type: ignore[arg-type]
    chunker = Chunker()
    drafts = chunker.feed(model.blocks) + chunker.flush()
    await write_index(session, DOC_ID, model.blocks, model.outline, drafts)  # type: ignore[arg-type]
    await session.commit()  # type: ignore[attr-defined]


async def _check_mapping(session: object, hits: list[Hit]) -> tuple[int, int]:
    """Every hit's block ids must resolve to blocks of the same document."""
    known = {
        row.id
        for row in await session.scalars(  # type: ignore[attr-defined]
            select(Block).where(Block.doc_id == DOC_ID)
        )
    }
    mapped = sum(1 for hit in hits if set(hit.block_ids) <= known)
    return mapped, len(hits)


async def _scope_isolation(session: object, embedder: Embedder) -> bool:
    """A second document's chunk must not appear under a `doc` scope.

    The planted chunk copies a real chunk's vector as well as being lexically
    tempting ("warmup steps and attention heads"), so it ranks first in *both*
    stages for the probe query. If either stage ignored the scope filter, this
    chunk would come back; with only its text it would only catch the lexical
    path.
    """
    seed = await session.scalar(  # type: ignore[attr-defined]
        select(Chunk.embedding).where(Chunk.doc_id == DOC_ID, Chunk.embedding.is_not(None)).limit(1)
    )
    session.add(  # type: ignore[attr-defined]
        Document(id="check-other", sha256="d" * 64, title="Other", status="ready", file_path="x")
    )
    session.add(  # type: ignore[attr-defined]
        Chunk(
            id="check-other:b1_1",
            doc_id="check-other",
            block_ids=["b1_1"],
            section_id="h1",
            page_start=1,
            page_end=1,
            text="warmup steps and attention heads and BLEU scores of the base model",
            embedding=seed,
        )
    )
    await session.commit()  # type: ignore[attr-defined]
    result = await retrieve(session, "warmup steps", Scope("doc", [DOC_ID]), embedder)  # type: ignore[arg-type]
    leaked = [hit for hit in result.hits if hit.doc_id != DOC_ID]
    return not leaked


async def main() -> int:
    settings = get_settings()
    embedder = Embedder(settings.embed_model, str(settings.model_dir))

    engine = db.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = db.get_session_factory()

    async with factory() as session:
        await session.execute(text("DELETE FROM documents WHERE id IN (:a, :b)"), {"a": DOC_ID, "b": "check-other"})
        await session.commit()

        started = time.time()
        await _prepare(session)
        chunks = await session.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.doc_id == DOC_ID)
        )
        print(f"chunks: {chunks}")

        result = await embed_document(session, DOC_ID, embedder)
        print(f"embedded {result.embedded} in {time.time() - started:.0f}s")
        if result.embedded == 0:
            print("R1: FAIL — nothing was embedded (model unavailable?)")
            return 1

        misses: list[str] = []
        for question, needle in GOLDEN:
            found = await retrieve(session, question, Scope("doc", [DOC_ID]), embedder)
            ok = any(needle.lower() in hit.text.lower() for hit in found.hits)
            if not ok:
                misses.append(question)
            mark = "ok  " if ok else "MISS"
            if found.hits:
                top = found.hits[0]
                print(
                    f"  {mark} {question[:56]:<56} top={top.score:.3f} p{top.page_start} "
                    f"stages={found.stages}"
                )
            else:
                print(f"  {mark} {question[:56]:<56} (no hits)")

        recall = 1.0 - len(misses) / len(GOLDEN)
        print(f"\nrecall@8 = {recall:.2f} over {len(GOLDEN)} questions")

        probe = await retrieve(session, "multi-head attention", Scope("doc", [DOC_ID]), embedder)
        mapped, total = await _check_mapping(session, probe.hits)
        print(f"chunk→block mapping: {mapped}/{total} hits resolved to real blocks")

        isolated = await _scope_isolation(session, embedder)
        print(f"scope isolation: {'ok' if isolated else 'LEAKED'}")

    await engine.dispose()
    verdict = "PASS" if recall >= MIN_RECALL and mapped == total and total and isolated else "FAIL"
    print(f"\nR1: {verdict} — recall {recall:.2f}, mapping {mapped}/{total}, scope {'ok' if isolated else 'leaked'}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
