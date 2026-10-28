"""Chinese → English academic translation (T7.4, 01 §5.3).

The endpoint behind this module takes an abstract or a short paper and
returns publishable academic English. It shares the block translator's
contract with formulas, but adds discipline a Chinese abstract needs:

  * long input is split on paragraph and sentence boundaries, never inside a
    ``$...$`` span, a code span or a citation, then translated four chunks at
    a time;
  * Latin technical terms (model names, acronyms) must survive; a model that
    drops one is asked once more with the missing terms quoted back at it;
  * results are memoised in-process, so pressing the button twice costs one
    model pass and returns ``cached=true`` (H06).

The contract for ``POST /translate/zh2en`` is synchronous, so input is capped
at 20,000 characters — a full book goes through the document job instead of
this endpoint (see QUESTIONS.md).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from ..llm.safety import system_with_guard
from .glossary import Glossary
from .service import translate_text

logger = logging.getLogger(__name__)

PROMPT_VERSION = "academic-v1"
MAX_INPUT_CHARS = 20_000
CHUNK_CHARS = 1_600
BATCH = 4
CACHE_MAX = 64

_SYSTEM = (
    "You are an academic translator for computer-science papers. Translate the "
    "Simplified Chinese text into formal, concise academic English with the usual "
    "impersonal register (passive voice where natural, no rhetorical questions). "
    "Keep every number, formula, code span, citation marker and ⟦n⟧ placeholder "
    "exactly as written, once each. Keep model names, acronyms, symbols and "
    "established technical terms in their original form. Preserve the source's "
    "paragraph breaks. Do not add explanations, summaries, headings or translator "
    "notes; output only the English translation."
)
_STRICT = " These terms must appear verbatim in the translation: {terms}."

_SENTENCE = re.compile(r"(?<=[。！？；!?;])")
_TERM = re.compile(r"[A-Za-z][A-Za-z0-9+#_.\-]{2,}")
_STOP = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "this",
    "that",
    "are",
    "was",
    "were",
    "not",
    "et al",
}

_CACHE: OrderedDict[str, str] = OrderedDict()


@dataclass(frozen=True)
class AcademicResult:
    text: str
    cached: bool


def clear_cache() -> None:
    """Drop memoised translations (tests and the acceptance tool use this)."""
    _CACHE.clear()


def _key(text: str, glossary_version: int = 0, glossary_fingerprint: str = "") -> str:
    stem = f"{PROMPT_VERSION}|zh2en|{text}"
    if glossary_version or glossary_fingerprint:
        stem = f"{PROMPT_VERSION}|g{glossary_version}|{glossary_fingerprint}|zh2en|{text}"
    return hashlib.sha256(stem.encode()).hexdigest()


def _remember(key: str, value: str) -> None:
    _CACHE[key] = value
    _CACHE.move_to_end(key)
    while len(_CACHE) > CACHE_MAX:
        _CACHE.popitem(last=False)


def _system(extra: str = "") -> str:
    return system_with_guard(_SYSTEM + extra)


def _safe_cut(text: str, limit: int) -> int:
    """A cut point at or after ``limit`` that does not split a protected span."""
    cut = max(1, min(limit, len(text) - 1))
    for opening, closing in (("$", "$"), ("`", "`"), ("\\[", "\\]"), ("\\(", "\\)"), ("[", "]")):
        before = text[:cut]
        inside = before.count(opening) % 2 == 1 if opening == closing else before.count(opening) > before.count(closing)
        if inside:
            close = text.find(closing, cut)
            if close != -1:
                cut = close + len(closing)
    # A Latin term cut in half ("Transfor|mer") cannot survive translation.
    while (
        cut < len(text)
        and text[cut - 1].isascii()
        and text[cut - 1].isalnum()
        and text[cut].isascii()
        and text[cut].isalnum()
    ):
        cut += 1
    return min(cut, len(text))


def _hard_split(text: str, limit: int) -> list[str]:
    pieces: list[str] = []
    remaining = text
    while len(remaining) > limit:
        cut = remaining.rfind(" ", limit // 2, limit)
        if cut == -1:
            cut = _safe_cut(remaining, limit)
        pieces.append(remaining[:cut].strip())
        remaining = remaining[cut:].lstrip()
    if remaining.strip():
        pieces.append(remaining.strip())
    return [piece for piece in pieces if piece]


def _paragraph_pieces(paragraph: str, limit: int) -> list[str]:
    if len(paragraph) <= limit:
        return [paragraph]
    pieces: list[str] = []
    buffer = ""
    for sentence in _SENTENCE.split(paragraph):
        if not sentence:
            continue
        if len(sentence) > limit:
            if buffer:
                pieces.append(buffer)
                buffer = ""
            pieces.extend(_hard_split(sentence, limit))
        elif len(buffer) + len(sentence) <= limit:
            buffer += sentence
        else:
            pieces.append(buffer)
            buffer = sentence
    if buffer:
        pieces.append(buffer)
    return [piece.strip() for piece in pieces if piece.strip()]


def chunk_text(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    """Split on paragraph, then sentence boundaries, keeping chunks ≤ limit."""
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text.strip()) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        for piece in _paragraph_pieces(paragraph, limit):
            if not current:
                current = piece
            elif len(current) + 2 + len(piece) <= limit:
                current = f"{current}\n\n{piece}"
            else:
                chunks.append(current)
                current = piece
    if current:
        chunks.append(current)
    return chunks


def missing_terms(source: str, translated: str) -> list[str]:
    """Latin terms in the source that vanished from the translation."""
    lowered = translated.lower()
    return sorted(
        {
            match.group(0)
            for match in _TERM.finditer(source)
            if match.group(0).lower() not in _STOP and match.group(0).lower() not in lowered
        }
    )


async def _translate_chunk(chunk: str, gateway: Any, glossary: Glossary | None) -> str:
    translated, _ = await translate_text(chunk, "zh2en", gateway, system=_system(), glossary=glossary)
    missing = missing_terms(chunk, translated)
    if not missing:
        return translated
    logger.info("academic translate: retrying a chunk for %d missing terms", len(missing))
    strict = _system(_STRICT.format(terms=", ".join(missing[:20])))
    retried, _ = await translate_text(chunk, "zh2en", gateway, system=strict, glossary=glossary)
    return retried


async def translate_academic(text: str, gateway: Any, *, glossary: Glossary | None = None) -> AcademicResult:
    """Translate a Chinese abstract or short paper into academic English."""
    value = text.strip()
    if not value:
        return AcademicResult("", False)
    if len(value) > MAX_INPUT_CHARS:
        raise ValueError(f"文本过长：最多 {MAX_INPUT_CHARS} 字符")

    version = glossary.version if glossary is not None else 0
    fingerprint = glossary.fingerprint() if glossary is not None and glossary.entries else ""
    key = _key(value, version, fingerprint)
    hit = _CACHE.get(key)
    if hit is not None:
        _CACHE.move_to_end(key)
        return AcademicResult(hit, True)

    chunks = chunk_text(value)
    if not chunks:
        return AcademicResult("", False)

    started = time.monotonic()
    semaphore = asyncio.Semaphore(BATCH)

    async def run(chunk: str) -> str:
        async with semaphore:
            return await _translate_chunk(chunk, gateway, glossary)

    pieces = await asyncio.gather(*(run(chunk) for chunk in chunks))
    translated = "\n\n".join(piece.strip() for piece in pieces if piece.strip()).strip()
    _remember(key, translated)
    logger.info(
        "academic translate: chars=%d chunks=%d elapsed_ms=%d",
        len(value),
        len(chunks),
        round((time.monotonic() - started) * 1000),
    )
    return AcademicResult(translated, False)
