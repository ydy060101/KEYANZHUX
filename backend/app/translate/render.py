"""Markdown/HTML rendering of stored translations (T4.2, T4.4).

Split out of `service.py` to keep each translation module under the file-size
limit (H14); the queries and formatting are unchanged. The render reads every
stored row for the document/language, so it is run after the translation job
has committed, never from the request that starts it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..ingest import storage
from ..models.orm import Block as BlockRow
from ..models.orm import Translation
from .service import LANG


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
