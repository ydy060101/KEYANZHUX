"""Check question answering end to end on the real models (T3.3, acceptance Q1).

The unit suite proves the mechanics with doubles. This script is the other
half: it loads the real bge-m3, bge-reranker-v2-m3 and the configured LLM,
indexes the fixture paper through the production path, and measures what the
card asks for on `tests/golden_qa.json`:

  * **anchor page accuracy** — for each answerable question, at least one
    citation must land on the page where the paper states the answer
    (the initial target is 90%);
  * **refusal rate** — every question the paper cannot answer must be refused
    (the target is 100%);
  * **point hit rate** — informational: does the answer contain the expected
    fact at all?

The golden file's needles and pages were checked against the fixture's own
text, not copied from a model run, and the script prints each question's
pages rather than only a total (H05, H06).

Run from `backend/`:

    .venv/Scripts/python.exe -I tools/check_qa.py

It prints a verdict line starting `Q1:` so the result is greppable.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

# Answer text contains symbols a Windows console encodes as GBK.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import func, select, text  # noqa: E402

from app import db  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.ingest.parser import parse_pdf  # noqa: E402
from app.llm.gateway import get_gateway  # noqa: E402
from app.models.orm import Base, Chunk, Document  # noqa: E402
from app.qa.answer import run_qa  # noqa: E402
from app.rag.chunk import Chunker  # noqa: E402
from app.rag.embed_pass import embed_document  # noqa: E402
from app.rag.embedding import Embedder  # noqa: E402
from app.rag.index import write_index  # noqa: E402
from app.rag.retrieve import Scope  # noqa: E402
from app.workers.persist import persist_parse  # noqa: E402

PDF = BACKEND / "fixtures" / "pdf" / "1706.03762v1.pdf"
DOC_ID = "check-qa"
GOLDEN = json.loads((BACKEND / "tests" / "golden_qa.json").read_text(encoding="utf-8"))
MIN_ANCHOR = 0.90


async def _prepare(session: Any) -> None:
    model = parse_pdf(PDF, DOC_ID).model
    session.add(
        Document(
            id=DOC_ID,
            sha256="c" * 64,
            title=GOLDEN["documents"]["transformer"]["title"],
            status="ready",
            page_count=model.page_count,
            file_path=str(PDF),
        )
    )
    await session.flush()
    await persist_parse(session, model)
    chunker = Chunker()
    drafts = chunker.feed(model.blocks) + chunker.flush()
    await write_index(session, DOC_ID, model.blocks, model.outline, drafts)
    await session.commit()


async def _ask(session: Any, question: str, embedder: Embedder, gateway: Any) -> Any:
    return await run_qa(
        session, question, Scope("doc", [DOC_ID]), embedder=embedder, gateway=gateway
    )


def _point_hit(answer: str, points: list[str]) -> bool:
    lowered = answer.lower()
    return all(point.lower() in lowered for point in points)


async def _measure_answerable(session: Any, embedder: Embedder, gateway: Any) -> tuple[int, int]:
    correct = 0
    hits = 0
    entries = GOLDEN["entries"]
    for index, entry in enumerate(entries, start=1):
        outcome = await _ask(session, entry["question"], embedder, gateway)
        answer = outcome.answer
        pages = [citation.anchor.page for citation in answer.citations]
        anchor_ok = not answer.refused and any(page in entry["expected_pages"] for page in pages)
        point_ok = not answer.refused and _point_hit(answer.answer, entry["expected_points"])
        correct += int(anchor_ok)
        hits += int(point_ok)
        mark = "ok  " if anchor_ok else ("MISS" if not answer.refused else "REF ")
        print(
            f"  {index:02d} {entry['id']} {mark} expected={entry['expected_pages']} "
            f"pages={pages} points={'ok' if point_ok else 'no '} top={outcome.stages.get('top_score')} "
            f"| {answer.answer[:90]}",
            flush=True,
        )
    return correct, hits


async def _measure_unanswerable(session: Any, embedder: Embedder, gateway: Any) -> int:
    refused = 0
    entries = GOLDEN["unanswerable"]
    for index, entry in enumerate(entries, start=1):
        outcome = await _ask(session, entry["question"], embedder, gateway)
        answer = outcome.answer
        refused += int(answer.refused)
        reason = outcome.stages.get("refusal", "-")
        print(
            f"  u{index:02d} {entry['id']} {'refused' if answer.refused else 'ANSWERED'} "
            f"top={outcome.stages.get('top_score')} reason={reason} | {answer.answer[:80]}",
            flush=True,
        )
    return refused


async def main() -> int:
    settings = get_settings()
    embedder = Embedder(settings.embed_model, str(settings.model_dir))
    gateway = get_gateway()

    engine = db.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = db.get_session_factory()

    try:
        async with factory() as session:
            await session.execute(text("DELETE FROM documents WHERE id = :a"), {"a": DOC_ID})
            await session.commit()

            started = time.time()
            await _prepare(session)
            chunks = await session.scalar(
                select(func.count()).select_from(Chunk).where(Chunk.doc_id == DOC_ID)
            )
            embedded = await embed_document(session, DOC_ID, embedder)
            print(f"chunks: {chunks}, embedded: {embedded.embedded} in {time.time() - started:.0f}s")
            if embedded.embedded == 0:
                print("Q1: FAIL — nothing was embedded (model unavailable?)")
                return 1

            print("\nanswerable questions:")
            correct, hits = await _measure_answerable(session, embedder, gateway)
            print("\nunanswerable questions:")
            refused = await _measure_unanswerable(session, embedder, gateway)
    finally:
        await gateway.close()
        await engine.dispose()

    total = len(GOLDEN["entries"])
    unknown = len(GOLDEN["unanswerable"])
    anchor_rate = correct / total
    refusal_rate = refused / unknown
    verdict = "PASS" if anchor_rate >= MIN_ANCHOR and refusal_rate == 1.0 else "FAIL"
    print(
        f"\nanchor page accuracy: {correct}/{total} = {anchor_rate:.2f} (target >= {MIN_ANCHOR:.2f})"
    )
    print(f"refusal rate: {refused}/{unknown} = {refusal_rate:.2f} (target 1.00)")
    print(f"point hit rate (informational): {hits}/{total} = {hits / total:.2f}")
    print(
        f"\nQ1: {verdict} — anchor {anchor_rate:.2f}, refusal {refusal_rate:.2f}, points {hits / total:.2f}"
    )
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
