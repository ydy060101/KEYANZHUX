"""Check question answering end to end on the real models.

The unit suite proves the mechanics with doubles. This script is the other
half: it loads the real bge-m3, bge-reranker-v2-m3 and the configured LLM,
indexes the fixture papers through the production path, and measures what the
cards ask for.

**Q1 (T3.3) — single-document QA** on `tests/golden_qa.json`:

  * anchor page accuracy — for each answerable question, at least one citation
    must land on the page where the paper states the answer (target 90%);
  * refusal rate — every question the paper cannot answer must be refused
    (target 100%);
  * point hit rate — informational: does the answer contain the expected fact?

**C1 (T3.4) — multi-document comparison**: Transformer, BERT and GPT-3 are
compared on fixed dimensions. Every grounded cell must carry an anchor that
resolves to a block containing the cell's text verbatim, every empty cell must
carry none, and enough cells must be grounded for the table to be a real
comparison rather than a wall of "未在原文找到".

01's acceptance names GPT-1/2/3; those PDFs are not staged and their host
(openai.com) is outside H09's downloader whitelist, so the third column is
GPT-3, the one GPT paper available on arXiv. `QUESTIONS.md` records this.

The golden file's needles and pages were checked against the fixture's own
text, not copied from a model run, and the script prints each question's pages
rather than only a total (H05, H06).

Run from `backend/`:

    .venv/Scripts/python.exe -I tools/check_qa.py            # both suites
    .venv/Scripts/python.exe -I tools/check_qa.py qa         # Q1 only
    .venv/Scripts/python.exe -I tools/check_qa.py compare    # C1 only

It prints verdict lines starting `Q1:` / `C1:` so results are greppable.
"""

from __future__ import annotations

import asyncio
import hashlib
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
from app.models.orm import Base, Block, Chunk, Document  # noqa: E402
from app.qa.answer import run_qa  # noqa: E402
from app.qa.compare import NOT_FOUND, run_compare  # noqa: E402
from app.qa.verify import grounds  # noqa: E402
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

COMPARE_PDFS = {
    "check-transformer": (PDF, GOLDEN["documents"]["transformer"]["title"]),
    "check-bert": (
        BACKEND / "fixtures" / "pdf" / "1810.04805_bert.pdf",
        "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
    ),
    "check-gpt3": (
        BACKEND / "fixtures" / "pdf" / "2005.14165_gpt3.pdf",
        "Language Models are Few-Shot Learners",
    ),
}
COMPARE_DIMENSIONS = [
    "model architecture",
    "number of layers",
    "hidden size",
    "attention mechanism",
]
COMPARE_QUESTION = (
    "Compare the model architecture, number of layers, hidden size and attention "
    "mechanism of these papers."
)
MIN_FOUND_COMPARE = 0.4


async def _prepare_document(session: Any, doc_id: str, pdf: Path, title: str) -> None:
    model = parse_pdf(pdf, doc_id).model
    # A synthetic but unique digest: the dev database also holds documents from
    # other checks and the user's own library, and a real file hash could
    # collide with a row this script must not touch.
    digest = hashlib.sha256(doc_id.encode("utf-8")).hexdigest()
    session.add(
        Document(
            id=doc_id,
            sha256=digest,
            title=title,
            status="ready",
            page_count=model.page_count,
            file_path=str(pdf),
        )
    )
    await session.flush()
    await persist_parse(session, model)
    chunker = Chunker()
    drafts = chunker.feed(model.blocks) + chunker.flush()
    await write_index(session, doc_id, model.blocks, model.outline, drafts)
    await session.commit()


async def _prepare(session: Any) -> None:
    await _prepare_document(
        session, DOC_ID, PDF, GOLDEN["documents"]["transformer"]["title"]
    )


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


async def _run_qa_suite(session: Any, embedder: Embedder, gateway: Any) -> bool:
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
        return False

    print("\nanswerable questions:")
    correct, hits = await _measure_answerable(session, embedder, gateway)
    print("\nunanswerable questions:")
    refused = await _measure_unanswerable(session, embedder, gateway)

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
    return verdict == "PASS"


async def _cell_ok(session: Any, doc_id: str, cell: Any) -> bool:
    """H01 for one cell: every anchor is a real block that holds the value."""
    if cell.text == NOT_FOUND:
        return not cell.citations
    if not cell.citations:
        return False
    for anchor in cell.citations:
        if anchor.doc_id != doc_id:
            return False
        block = await session.scalar(
            select(Block).where(Block.doc_id == doc_id, Block.id == anchor.block_id)
        )
        if block is None:
            return False
        if anchor.page != block.page or list(anchor.bbox) != list(block.bbox or []):
            return False
        if not grounds(block.text or "", cell.text):
            return False
    return True


async def _run_compare_suite(session: Any, embedder: Embedder, gateway: Any) -> bool:
    doc_ids = list(COMPARE_PDFS)
    await session.execute(text("DELETE FROM documents WHERE id = ANY(:ids)"), {"ids": doc_ids})
    await session.commit()

    started = time.time()
    for doc_id, (pdf, title) in COMPARE_PDFS.items():
        await _prepare_document(session, doc_id, pdf, title)
    for doc_id in doc_ids:
        embedded = await embed_document(session, doc_id, embedder)
        print(f"{doc_id}: {embedded.embedded} chunks embedded", flush=True)
        if embedded.embedded == 0:
            print("C1: FAIL — nothing was embedded (model unavailable?)")
            return False
    print(f"indexed {len(doc_ids)} papers in {time.time() - started:.0f}s")

    outcome = await run_compare(
        session,
        COMPARE_QUESTION,
        Scope("set", doc_ids),
        embedder=embedder,
        gateway=gateway,
        dimensions=COMPARE_DIMENSIONS,
    )
    table = outcome.table
    if table is None:
        print("C1: FAIL — no table was produced")
        return False

    print("\ncomparison table:")
    total = 0
    found = 0
    ok = 0
    for row in table.table:
        for doc_id in doc_ids:
            cell = row.cells[doc_id]
            total += 1
            found += int(cell.text != NOT_FOUND)
            cell_ok = await _cell_ok(session, doc_id, cell)
            ok += int(cell_ok)
            pages = [anchor.page for anchor in cell.citations]
            print(
                f"  {doc_id:17s} | {row.dimension:22s} | "
                f"{'ok  ' if cell_ok else 'FAIL'} | {cell.text[:48]:48s} | pages={pages}",
                flush=True,
            )
    found_rate = found / total
    anchored_rate = ok / total
    if table.flags:
        print("\nflags:")
        for flag in table.flags:
            print(f"  {flag.kind}: {flag.text}")
    verdict = "PASS" if ok == total and found_rate >= MIN_FOUND_COMPARE else "FAIL"
    print(f"\nsummary: {table.summary}")
    print(
        f"grounded cells: {found}/{total} = {found_rate:.2f} (target >= {MIN_FOUND_COMPARE:.2f})"
    )
    print(f"cells with correct provenance: {ok}/{total} = {anchored_rate:.2f} (target 1.00)")
    print(f"\nC1: {verdict} — grounded {found_rate:.2f}, provenance {anchored_rate:.2f}")
    return verdict == "PASS"


async def main() -> int:
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "all"
    if mode not in {"all", "qa", "compare"}:
        print(f"usage: {Path(__file__).name} [all|qa|compare]")
        return 2

    settings = get_settings()
    embedder = Embedder(settings.embed_model, str(settings.model_dir))
    gateway = get_gateway()

    engine = db.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = db.get_session_factory()

    results: dict[str, bool] = {}
    try:
        async with factory() as session:
            if mode in {"all", "qa"}:
                results["Q1"] = await _run_qa_suite(session, embedder, gateway)
            if mode in {"all", "compare"}:
                results["C1"] = await _run_compare_suite(session, embedder, gateway)
    finally:
        await gateway.close()
        await engine.dispose()

    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
