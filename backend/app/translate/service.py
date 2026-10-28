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
import hashlib
import logging
import time
from collections.abc import AsyncIterator, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..ingest import storage
from ..llm.safety import wrap_data
from ..models.orm import Block as BlockRow
from ..models.orm import Document, Translation
from .protect import hold_point, integrity, protect, restore, split_segments

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v1"
LANG = {"en2zh": "zh", "zh2en": "en"}
TRANSLATABLE = ("paragraph", "heading", "caption")
MAX_BLOCKS = 20_000
BATCH = 4
MIN_CHARS = 2

_SYSTEM = (
    "Translate research-paper text from {src} into {dst}. "
    "Keep every number, term and placeholder (⟦0⟧) exactly as written, once each. "
    "Output only the translation."
)
_DIRECTION = {
    "en2zh": ("English", "Simplified Chinese"),
    "zh2en": ("Simplified Chinese", "academic English"),
}


def _messages(text: str, direction: str) -> list[dict[str, str]]:
    src, dst = _DIRECTION[direction]
    return [
        {"role": "system", "content": _SYSTEM.format(src=src, dst=dst)},
        {
            "role": "user",
            "content": f"Translate the text between the markers.\n{wrap_data(text)}",
        },
    ]


def cache_key(text: str, direction: str) -> str:
    payload = f"{PROMPT_VERSION}|{direction}|{text}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _translate_masked(text: str, direction: str, gateway: Any) -> str:
    """One non-streaming call over already-masked text."""
    result = await gateway.chat(_messages(text, direction), tier="fast", temperature=0.0)
    return str(getattr(result, "text", result))


async def translate_text(text: str, direction: str, gateway: Any) -> tuple[str, bool]:
    """Translate a block; returns (text, repaired).

    ``repaired`` is True when the model broke a placeholder and the fallback
    had to translate the prose segments one by one.
    """
    if not text.strip():
        return text, False
    protected = protect(text)
    raw = await _translate_masked(protected.masked, direction, gateway)
    missing, duplicated = integrity(raw, protected.items)
    if not missing and not duplicated:
        return restore(raw, protected.items), False

    logger.warning(
        "translate: placeholder integrity broken (missing=%s duplicated=%s); using segments",
        missing,
        duplicated,
    )
    return await _translate_segments(text, direction, gateway), True


async def _translate_segments(text: str, direction: str, gateway: Any) -> str:
    """Translate only the prose between protected spans; spans are copied."""
    out: list[str] = []
    for chunk, protected in split_segments(text):
        if protected or not chunk.strip():
            out.append(chunk)
            continue
        out.append(await _translate_masked(chunk, direction, gateway))
    return "".join(out)


async def stream_translation(text: str, direction: str, gateway: Any) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Yield ``token`` events, then one ``done`` with the authoritative text.

    Tokens are restored as they arrive (a partial placeholder is held back).
    If the model breaks a placeholder, the final ``done.text`` is the
    repaired translation; the UI replaces what it streamed.
    """
    started = time.monotonic()
    protected = protect(text)
    pieces = await gateway.chat(_messages(protected.masked, direction), tier="fast", stream=True)
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
        final = await _translate_segments(text, direction, gateway)
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


async def translate_document(
    session: AsyncSession,
    doc_id: str,
    direction: str,
    gateway: Any,
    *,
    on_progress: Any = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Translate every text block of a document; resumable and idempotent.

    `limit` exists for the acceptance tool, which translates a handful of real
    blocks to check the formulas without paying for a whole paper (H06); the
    job never passes it.
    """
    doc = await session.get(Document, doc_id)
    if doc is None:
        raise ValueError(f"文档不存在：{doc_id}")
    lang = LANG[direction]
    rows = (
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
    existing = {
        row.block_id: row
        for row in (
            await session.execute(select(Translation).where(Translation.doc_id == doc_id, Translation.lang == lang))
        )
        .scalars()
        .all()
    }

    translated = 0
    cached = 0
    repaired = 0
    skipped = 0
    done = 0
    pending: list[BlockRow] = []
    for block in rows:
        key = cache_key(block.text, direction)
        row = existing.get(block.id)
        if row is not None and row.cache_key == key:
            cached += 1
            done += 1
            continue
        if len(block.text.strip()) < MIN_CHARS:
            skipped += 1
            done += 1
            continue
        pending.append(block)

    for start in range(0, len(pending), BATCH):
        batch = pending[start : start + BATCH]
        results = await asyncio.gather(*(translate_text(block.text, direction, gateway) for block in batch))
        for block, (text, was_repaired) in zip(batch, results, strict=True):
            row = existing.get(block.id)
            if row is None:
                row = Translation(
                    id=f"{doc_id}:{block.id}:{lang}",
                    doc_id=doc_id,
                    block_id=block.id,
                    lang=lang,
                    text=text,
                    cache_key=cache_key(block.text, direction),
                )
                session.add(row)
                existing[block.id] = row
            else:
                row.text = text
                row.cache_key = cache_key(block.text, direction)
            translated += 1
            repaired += int(was_repaired)
        await session.flush()
        done += len(batch)
        if on_progress is not None:
            await on_progress(done, len(rows))

    await session.commit()
    result = {
        "doc_id": doc_id,
        "direction": direction,
        "lang": lang,
        "blocks": len(rows),
        "translated": translated,
        "cached": cached,
        "repaired": repaired,
        "skipped": skipped,
    }
    logger.info("translate job done doc_id=%s translated=%d cached=%d", doc_id, translated, cached)
    return result


async def render_document(session: AsyncSession, doc_id: str, direction: str, fmt: str) -> dict[str, Any]:
    """Render the stored translation as Markdown or HTML, block by block."""
    lang = LANG[direction]
    rows = (
        await session.execute(
            select(BlockRow, Translation)
            .join(Translation, (Translation.doc_id == BlockRow.doc_id) & (Translation.block_id == BlockRow.id))
            .where(BlockRow.doc_id == doc_id, Translation.lang == lang)
            .order_by(BlockRow.page, BlockRow.reading_order)
        )
    ).all()
    content = _to_html(rows) if fmt == "html" else _to_markdown(rows)
    path = storage.translation_dir(doc_id) / f"{doc_id}.{lang}.{fmt}"
    path.write_text(content, encoding="utf-8")
    return {
        "doc_id": doc_id,
        "direction": direction,
        "format": fmt,
        "path": str(path),
        "blocks": len(rows),
        "content": content,
    }


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _to_markdown(rows: Sequence[Any]) -> str:
    parts: list[str] = []
    for block, translation in rows:
        text = translation.text.strip()
        if not text:
            continue
        if block.type == "heading":
            parts.append(f"## {text}")
        elif block.type == "caption":
            parts.append(f"*{text}*")
        else:
            parts.append(text)
    return "\n\n".join(parts) + ("\n" if parts else "")


def _to_html(rows: Sequence[Any]) -> str:
    parts: list[str] = []
    for block, translation in rows:
        text = _escape_html(translation.text.strip())
        if not text:
            continue
        tag = "h2" if block.type == "heading" else "figcaption" if block.type == "caption" else "p"
        parts.append(f"<{tag}>{text}</{tag}>")
    return "\n".join(parts) + ("\n" if parts else "")
