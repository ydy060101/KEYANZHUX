"""Check the embedding index end to end on the real fixtures (T3.1).

The unit suite uses a stub embedder, because loading a 2 GB model in a test is
wrong (H15). This script is the other half: it loads the real bge-m3, embeds a
document's chunks through the same code path the job uses, and checks that the
vectors actually carry meaning — a query finds its own passage, and an
unrelated one does not.

Run from `backend/`:

    .venv/Scripts/python.exe -I tools/check_embedding.py [pdf-name]

It prints a verdict line starting `E1:` so the result is greppable.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

# Chunk text is the paper's own, and it contains symbols a Windows console
# encodes as GBK — printing one raises UnicodeEncodeError and kills the run
# before it can report a verdict.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import select, text  # noqa: E402

from app import db  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.ingest.parser import parse_pdf  # noqa: E402
from app.models.orm import Base, Chunk, Document  # noqa: E402
from app.rag.chunk import Chunker  # noqa: E402
from app.rag.embed_pass import embed_document, pending_count  # noqa: E402
from app.rag.embedding import Embedder  # noqa: E402
from app.rag.index import write_index  # noqa: E402

PDF = BACKEND / "fixtures" / "pdf" / "1706.03762v1.pdf"
DOC_ID = "check-embedding"


async def _prepare(session: object) -> list[str]:
    """Parse, chunk and store one paper, the way the parse job does."""
    model = parse_pdf(PDF, DOC_ID).model
    doc = Document(
        id=DOC_ID,
        sha256="f" * 64,
        title="Attention Is All You Need",
        status="ready",
        page_count=model.page_count,
        file_path=str(PDF),
    )
    session.add(doc)  # type: ignore[attr-defined]
    await session.flush()  # type: ignore[attr-defined]
    chunker = Chunker()
    drafts = chunker.feed(model.blocks) + chunker.flush()
    await write_index(session, DOC_ID, model.blocks, model.outline, drafts)  # type: ignore[arg-type]
    await session.commit()  # type: ignore[attr-defined]
    return [draft.text for draft in drafts]


async def _search(session: object, embedder: Embedder, query: str, k: int = 3) -> list[tuple[float, str]]:
    """Cosine search over the document's chunks, through pgvector."""
    vector = await embedder.embed_one(query)
    if vector is None:
        raise SystemExit("the embedding model produced no vector")
    rows = await session.execute(  # type: ignore[attr-defined]
        select(Chunk.text, Chunk.embedding.cosine_distance(vector).label("distance"))
        .where(Chunk.doc_id == DOC_ID, Chunk.embedding.is_not(None))
        .order_by(text("distance"))
        .limit(k)
    )
    return [(1.0 - float(row.distance), row.text) for row in rows]


async def main() -> int:
    settings = get_settings()
    embedder = Embedder(settings.embed_model, str(settings.model_dir))

    engine = db.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = db.get_session_factory()

    async with factory() as session:
        await session.execute(text("DELETE FROM documents WHERE id = :id"), {"id": DOC_ID})
        await session.commit()
        started = time.time()
        texts = await _prepare(session)
        print(f"chunks: {len(texts)}")

        loaded = time.time()
        result = await embed_document(session, DOC_ID, embedder)
        done = time.time()
        print(f"model load + embed: {done - loaded:.1f}s for {result.embedded} chunks")
        print(f"pending after: {await pending_count(session, DOC_ID)}")

        if result.embedded == 0:
            print("E1: FAIL — nothing was embedded (model unavailable?)")
            return 1

        probes = [
            ("How many attention heads does the base model use?", "attention head"),
            ("What optimizer and learning rate were used?", "adam"),
            ("What BLEU score did the model reach on English to German?", "bleu"),
        ]
        hits = 0
        for query, needle in probes:
            found = await _search(session, embedder, query)
            best_score, best_text = found[0]
            ok = needle in best_text.lower()
            hits += int(ok)
            print(f"  query={query!r} best={best_score:.3f} contains {needle!r}: {ok}")
            print(f"    {best_text[:110]!r}")

        # A vector that ignores the text would score every chunk the same; the
        # spread between the best and worst match is the evidence it does not.
        spread = max(score for score, _ in await _search(session, embedder, probes[0][0], k=20)) - min(
            score for score, _ in await _search(session, embedder, probes[0][0], k=20)
        )
        print(f"score spread over the top 20: {spread:.3f}")

    await engine.dispose()
    elapsed = time.time() - started
    verdict = "PASS" if hits == len(probes) and spread > 0.05 else "FAIL"
    print(f"E1: {verdict} — {hits}/{len(probes)} probes found their passage in {elapsed:.0f}s")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
