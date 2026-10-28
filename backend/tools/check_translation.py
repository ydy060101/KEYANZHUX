"""Check translation end to end with the real model (T4.1/T4.2).

The unit suite proves the mechanics with a deterministic double; this script
is the other half, run against the real DeepSeek gateway:

  * **T1** — a selection with formulas streams its first token in ≤ 1.5 s and
    the finished text still contains every ``$...$`` span byte for byte;
  * **T2** — a real formula-bearing block keeps its LaTeX, and translating a
    handful of blocks twice reports the second pass as fully cached.

Run from `backend/` with the API up:

    .venv/Scripts/python.exe -I tools/check_translation.py

It prints verdict lines starting `T1:` / `T2:` so the result is greppable.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402

from app import db  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.llm.gateway import get_gateway  # noqa: E402
from app.models.orm import Block, Document, Translation  # noqa: E402
from app.translate.protect import split_segments  # noqa: E402
from app.translate.service import translate_document, translate_text  # noqa: E402

API = "http://127.0.0.1:8000/api/v1"
CHECK_DOC = "check-translation"
SAMPLE = (
    "We train the base model with $d_{model}=512$ and $h=8$ attention heads, "
    "following the schedule in [12]; the learning rate warms up over $4000$ steps."
)


def spans(value: str) -> list[str]:
    return [chunk for chunk, protected in split_segments(value) if protected and chunk.startswith("$")]


async def _one_selection(client: httpx.AsyncClient) -> tuple[float, float, dict[str, object]] | None:
    """One streamed selection; returns (first_token_ms, total_ms, done)."""
    first_ms: float | None = None
    done: dict[str, object] | None = None
    started = time.monotonic()
    async with client.stream(
        "POST",
        f"{API}/translate/selection",
        json={"text": SAMPLE, "direction": "en2zh"},
        headers={"Accept": "text/event-stream", "X-User-Id": "default"},
    ) as response:
        if response.status_code != 200:
            body = (await response.aread()).decode("utf-8", "replace")
            print(f"T1: FAIL — HTTP {response.status_code}: {body[:200]}")
            return None
        event = "message"
        async for line in response.aiter_lines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:].strip())
                if event == "token" and first_ms is None:
                    first_ms = (time.monotonic() - started) * 1000
                elif event == "done":
                    done = data
                elif event == "error":
                    print(f"T1: FAIL — {data}")
                    return None
    if done is None or first_ms is None:
        print("T1: FAIL — the stream ended without a token and a done event")
        return None
    return first_ms, (time.monotonic() - started) * 1000, done


async def _selection() -> bool:
    """Stream three selections; the median first token must be ≤ 1.5 s.

    One sample is not a latency measurement: the gateway's own time to first
    token moves by a few hundred milliseconds between calls. Every sample's
    formulas are checked; the timing verdict uses the median.
    """
    async with httpx.AsyncClient(timeout=60.0) as client:
        samples = [await _one_selection(client) for _ in range(3)]
    valid = [sample for sample in samples if sample is not None]
    if len(valid) != 3:
        return False
    firsts: list[float] = []
    formula_ok = True
    for first_ms, elapsed, done in valid:
        final = str(done.get("text", ""))
        source_spans = spans(SAMPLE)
        kept = [span for span in source_spans if span in final]
        formula_ok = formula_ok and len(kept) == len(source_spans) and "[12]" in final
        firsts.append(first_ms)
        print(
            f"  first token {first_ms:.0f} ms, whole stream {elapsed:.0f} ms, "
            f"repaired={done.get('repaired')}, formulas kept {len(kept)}/{len(source_spans)}"
        )
    firsts.sort()
    median = firsts[len(firsts) // 2]
    print(f"  translation: {str(valid[-1][2].get('text', ''))[:120]}")
    ok = median <= 1500 and formula_ok
    print(
        f"T1: {'PASS' if ok else 'FAIL'} — median first token {median:.0f} ms ≤ 1500 ms and every LaTeX span identical"
    )
    return ok


async def _document() -> bool:
    """Translate a mixed document; formulas must survive and the rerun must be cached."""
    engine = db.get_engine()
    factory = db.get_session_factory()
    gateway = get_gateway()
    ok = True
    async with factory() as session:
        # The parsed fixtures keep formulas as page crops, not as text, so the
        # document sample pairs the real-model selection above with five real
        # paragraphs: same job path, a formula the assertion can check.
        source = SAMPLE
        translated, repaired = await translate_text(source, "en2zh", gateway)
        kept = [span for span in spans(source) if span in translated]
        formula_ok = len(kept) == len(spans(source)) and len(spans(source)) > 0
        print(f"  sample: {len(spans(source))} formula spans, kept {len(kept)}, repaired={repaired}")
        print(f"  translation: {translated[:140]}")
        ok = ok and formula_ok

        row = (
            await session.execute(
                select(Block.doc_id)
                .where(Block.type == "paragraph", func.length(Block.text) > 80)
                .group_by(Block.doc_id)
                .order_by(func.count().desc())
                .limit(1)
            )
        ).first()
        if row is None:
            print("T2: FAIL — no document with enough paragraphs to sample")
            return False
        doc_id = row[0]
        real_blocks = (
            (
                await session.execute(
                    select(Block)
                    .where(Block.doc_id == doc_id, Block.type == "paragraph", func.length(Block.text) > 80)
                    .order_by(Block.reading_order)
                    .limit(5)
                )
            )
            .scalars()
            .all()
        )
        if len(real_blocks) < 5:
            print("T2: FAIL — the sampled document has too few paragraphs")
            return False

        # A six-block synthetic document, rebuilt on every run: the cache
        # assertions need a first pass that really translates something.
        await session.execute(text("DELETE FROM documents WHERE id = :id"), {"id": CHECK_DOC})
        check = Document(
            id=CHECK_DOC,
            sha256="9" * 64,
            title="Translation check",
            status="uploading",
            file_path="unused.pdf",
            page_count=1,
        )
        session.add(check)
        session.add(
            Block(
                doc_id=CHECK_DOC,
                id="b1_1",
                type="paragraph",
                page=1,
                bbox=[0, 0, 100, 100],
                reading_order=1,
                text=SAMPLE,
            )
        )
        for index, original in enumerate(real_blocks, start=2):
            session.add(
                Block(
                    doc_id=CHECK_DOC,
                    id=f"b1_{index}",
                    type="paragraph",
                    page=1,
                    bbox=list(original.bbox),
                    reading_order=index,
                    text=original.text,
                )
            )
        await session.commit()

        first = await translate_document(session, CHECK_DOC, "en2zh", gateway)
        second = await translate_document(session, CHECK_DOC, "en2zh", gateway)
        pairs = (
            await session.execute(
                select(Block.text, Translation.text)
                .join(Translation, (Translation.doc_id == Block.doc_id) & (Translation.block_id == Block.id))
                .where(Block.doc_id == CHECK_DOC, Translation.lang == "zh")
            )
        ).all()
        cache_ok = first["translated"] == 6 and second["cached"] == 6 and second["translated"] == 0
        sample_row = (
            await session.execute(
                select(Translation.text).where(Translation.doc_id == CHECK_DOC, Translation.block_id == "b1_1")
            )
        ).scalar_one_or_none()
        sample_ok = sample_row is not None and all(span in sample_row for span in spans(SAMPLE))
        stored_ok = all(all(span in translation for span in spans(original)) for original, translation in pairs)
        print(f"  first pass translated={first['translated']} cached={first['cached']}")
        print(f"  second pass translated={second['translated']} cached={second['cached']}")
        print(f"  stored rows {len(pairs)}; sample formulas in its stored row: {sample_ok}")
        print(f"  stored formula check over every row: {stored_ok}")
        ok = ok and cache_ok and stored_ok and sample_ok
    await engine.dispose()
    print(f"T2: {'PASS' if ok else 'FAIL'} — formulas byte-identical and the rerun hits the block cache")
    return ok


async def main() -> int:
    settings = get_settings()
    print(f"gateway: {settings.llm_base_url} (fast={settings.llm_fast})")
    t1 = await _selection()
    t2 = await _document()
    print(f"translation: {'PASS' if t1 and t2 else 'FAIL'}")
    return 0 if t1 and t2 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
