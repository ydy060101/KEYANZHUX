"""Selection and whole-document translation (T4.1, T4.2).

Both paths run through the same discipline:

  * the text is masked by :mod:`protect` before the call, so formulas, code
    and citation markers come back exactly as printed;
  * the finished translation is checked for placeholder integrity, and a
    model that dropped or repeated one triggers a per-segment retry that
    cannot lose a formula;
  * the call is `fast` and ``temperature=0`` — translation is extraction-like
    work, and H06 asks for the same input to produce the same output.

The document path stores one row per block in `translations`, keyed by a hash
of the source text, direction and prompt version. A re-run reuses rows whose
key still matches, so translating a 500-page book twice costs one pass.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.orm import Block as BlockRow
from ..models.orm import Document, Translation
from .glossary import Glossary
from .prompt import cache_key, messages, system_for
from .protect import hold_point, integrity, protect, restore, split_segments

logger = logging.getLogger(__name__)

LANG = {"en2zh": "zh", "zh2en": "en"}
TRANSLATABLE = ("paragraph", "heading", "caption")
MAX_BLOCKS = 20_000
BATCH = 4
MIN_CHARS = 2


async def _translate_masked(text: str, direction: str, gateway: Any, *, system: str | None = None) -> str:
    """One non-streaming call over already-masked text."""
    result = await gateway.chat(messages(text, direction, system), tier="fast", temperature=0.0)
    return str(getattr(result, "text", result))


async def translate_text(
    text: str,
    direction: str,
    gateway: Any,
    *,
    system: str | None = None,
    glossary: Glossary | None = None,
) -> tuple[str, bool]:
    """Translate a block; returns (text, repaired).

    ``repaired`` is True when the model broke a placeholder and the fallback
    had to translate the prose segments one by one.
    """
    if not text.strip():
        return text, False
    protected = protect(text)
    prompt = system_for(direction, text, glossary, system)
    raw = await _translate_masked(protected.masked, direction, gateway, system=prompt)
    missing, duplicated = integrity(raw, protected.items)
    if not missing and not duplicated:
        return restore(raw, protected.items), False

    logger.warning(
        "translate: placeholder integrity broken (missing=%s duplicated=%s); using segments",
        missing,
        duplicated,
    )
    return await _translate_segments(text, direction, gateway, prompt), True


async def _translate_segments(text: str, direction: str, gateway: Any, system: str) -> str:
    """Translate only the prose between protected spans; spans are copied."""
    out: list[str] = []
    for chunk, protected in split_segments(text):
        if protected or not chunk.strip():
            out.append(chunk)
            continue
        out.append(await _translate_masked(chunk, direction, gateway, system=system))
    return "".join(out)


async def stream_translation(
    text: str, direction: str, gateway: Any, *, glossary: Glossary | None = None
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Yield ``token`` events, then one ``done`` with the authoritative text.

    Tokens are restored as they arrive (a partial placeholder is held back).
    If the model breaks a placeholder, the final ``done.text`` is the
    repaired translation; the UI replaces what it streamed.
    """
    started = time.monotonic()
    protected = protect(text)
    prompt = system_for(direction, text, glossary)
    pieces = await gateway.chat(messages(protected.masked, direction, prompt), tier="fast", stream=True)
    buffer = ""
    masked: list[str] = []
    first_at: float | None = None
    async for piece in pieces:
        buffer += piece
        cut = hold_point(buffer)
        if cut == 0:
            continue
        masked.append(buffer[:cut])
        out = restore(buffer[:cut], protected.items)
        buffer = buffer[cut:]
        if first_at is None:
            first_at = time.monotonic() - started
        yield "token", {"text": out}
    if buffer:
        masked.append(buffer)
        out = restore(buffer, protected.items)
        if first_at is None:
            first_at = time.monotonic() - started
        yield "token", {"text": out}

    # Integrity is checked on the masked stream: after `restore` the markers
    # are gone by design, and checking then would call every translation broken.
    missing, duplicated = integrity("".join(masked), protected.items)
    repaired = bool(missing or duplicated)
    final = restore("".join(masked), protected.items)
    if repaired:
        logger.warning("translate: stream broke a placeholder; repairing with segments")
        final = await _translate_segments(text, direction, gateway, prompt)
    yield (
        "done",
        {
            "text": final,
            "direction": direction,
            "repaired": repaired,
            "placeholders": len(protected.items),
            "first_token_ms": None if first_at is None else round(first_at * 1000),
            "elapsed_ms": round((time.monotonic() - started) * 1000),
        },
    )


# ---- whole document ------------------------------------------------------


async def _document_blocks(session: AsyncSession, doc_id: str, limit: int | None) -> list[BlockRow]:
    return list(
        (
            await session.execute(
                select(BlockRow)
                .where(
                    BlockRow.doc_id == doc_id,
                    BlockRow.type.in_(TRANSLATABLE),
                    BlockRow.text != "",
                )
                .order_by(BlockRow.page, BlockRow.reading_order)
                .limit(min(MAX_BLOCKS, limit) if limit else MAX_BLOCKS)
            )
        )
        .scalars()
        .all()
    )


async def _stored_translations(session: AsyncSession, doc_id: str, lang: str) -> dict[str, Translation]:
    return {
        row.block_id: row
        for row in (
            await session.execute(select(Translation).where(Translation.doc_id == doc_id, Translation.lang == lang))
        )
        .scalars()
        .all()
    }


def _partition(
    rows: Sequence[BlockRow],
    existing: dict[str, Translation],
    key_for: Any,
) -> tuple[list[BlockRow], int, int]:
    """Split blocks into (to translate, cached, skipped)."""
    pending: list[BlockRow] = []
    cached = 0
    skipped = 0
    for block in rows:
        row = existing.get(block.id)
        if row is not None and row.cache_key == key_for(block.text):
            cached += 1
            continue
        if len(block.text.strip()) < MIN_CHARS:
            skipped += 1
            continue
        pending.append(block)
    return pending, cached, skipped


async def _translate_batch(
    session: AsyncSession,
    doc_id: str,
    lang: str,
    batch: Sequence[BlockRow],
    existing: dict[str, Translation],
    direction: str,
    gateway: Any,
    glossary: Glossary | None,
    key_for: Any,
) -> tuple[int, int]:
    """Translate one batch, storing each block under the same key."""
    results = await asyncio.gather(
        *(translate_text(block.text, direction, gateway, glossary=glossary) for block in batch)
    )
    translated = 0
    repaired = 0
    for block, (text, was_repaired) in zip(batch, results, strict=True):
        row = existing.get(block.id)
        if row is None:
            row = Translation(
                id=f"{doc_id}:{block.id}:{lang}",
                doc_id=doc_id,
                block_id=block.id,
                lang=lang,
                text=text,
                cache_key=key_for(block.text),
            )
            session.add(row)
            existing[block.id] = row
        else:
            row.text = text
            row.cache_key = key_for(block.text)
        translated += 1
        repaired += int(was_repaired)
    await session.flush()
    return translated, repaired


async def _run_batches(
    session: AsyncSession,
    doc_id: str,
    lang: str,
    pending: Sequence[BlockRow],
    existing: dict[str, Translation],
    direction: str,
    gateway: Any,
    glossary: Glossary | None,
    key_for: Any,
    done: int,
    total: int,
    on_progress: Any,
) -> tuple[int, int]:
    translated = 0
    repaired = 0
    for start in range(0, len(pending), BATCH):
        batch = pending[start : start + BATCH]
        count, fixed = await _translate_batch(
            session, doc_id, lang, batch, existing, direction, gateway, glossary, key_for
        )
        translated += count
        repaired += fixed
        done += len(batch)
        if on_progress is not None:
            await on_progress(done, total)
    return translated, repaired


async def translate_document(
    session: AsyncSession,
    doc_id: str,
    direction: str,
    gateway: Any,
    *,
    on_progress: Any = None,
    limit: int | None = None,
    glossary: Glossary | None = None,
) -> dict[str, Any]:
    """Translate every text block of a document; resumable and idempotent.

    `limit` exists for the acceptance tool, which translates a handful of real
    blocks to check the formulas without paying for a whole paper (H06); the
    job never passes it. `glossary` changes the cache key and the system
    prompt together, so an edited list cannot reuse a translation written
    under the old terms.
    """
    doc = await session.get(Document, doc_id)
    if doc is None:
        raise ValueError(f"文档不存在：{doc_id}")
    lang = LANG[direction]
    version = glossary.version if glossary is not None else 0
    fingerprint = glossary.fingerprint() if glossary is not None and glossary.entries else ""

    def key_for(text: str) -> str:
        return cache_key(text, direction, version, fingerprint)

    rows = await _document_blocks(session, doc_id, limit)
    existing = await _stored_translations(session, doc_id, lang)
    pending, cached, skipped = _partition(rows, existing, key_for)
    translated, repaired = await _run_batches(
        session,
        doc_id,
        lang,
        pending,
        existing,
        direction,
        gateway,
        glossary,
        key_for,
        cached + skipped,
        len(rows),
        on_progress,
    )
    await session.commit()
    result = _document_result(
        doc_id, direction, lang, len(rows), translated, cached, repaired, skipped, version
    )
    logger.info(
        "translate job done doc_id=%s translated=%d cached=%d glossary_v=%d",
        doc_id,
        translated,
        cached,
        version,
    )
    return result


def _document_result(
    doc_id: str,
    direction: str,
    lang: str,
    blocks: int,
    translated: int,
    cached: int,
    repaired: int,
    skipped: int,
    version: int,
) -> dict[str, Any]:
    return {
        "doc_id": doc_id,
        "direction": direction,
        "lang": lang,
        "blocks": blocks,
        "translated": translated,
        "cached": cached,
        "repaired": repaired,
        "skipped": skipped,
        "glossary_version": version,
    }
