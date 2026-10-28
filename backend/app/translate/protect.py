"""Keep formulas, code and citations out of the translator's reach (T4.2).

A translation must not touch a formula: the LaTeX in the translated block has
to be byte-identical to the source (03 T4.2's acceptance), and a model that
"tidies" ``$d_{model}=512$`` into ``$d_{model} = 512$`` or translates the
variable name has broken the paper. The same holds for code spans and for
citation markers, which are anchors into the bibliography.

So every protected span is replaced by a numbered placeholder before the call
and put back afterwards. Two guarantees are checked, not assumed:

  * :func:`integrity` reports a placeholder the model dropped or repeated;
  * :func:`split_segments` can re-translate only the prose between protected
    spans, which cannot lose a formula because the formulas never leave the
    process. That is the fallback when a model returns a broken placeholder.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

OPEN = "⟦"
CLOSE = "⟧"
PLACEHOLDER_RE = re.compile(r"⟦(\d+)⟧")

# Order matters: a fenced block is matched before the inline-code rule inside
# it, and display math before inline math (whose lookarounds would otherwise
# split `$$...$$` in two).
_PROTECTED_PATTERNS = [
    re.compile(r"```.*?```", re.S),
    re.compile(r"\$\$.*?\$\$", re.S),
    re.compile(r"\\\[.*?\\\]", re.S),
    re.compile(r"\\\(.*?\\\)", re.S),
    re.compile(r"(?<!\$)\$(?!\$)(?:\\.|[^$\\\n])+(?<!\$)\$(?!\$)"),
    re.compile(r"`[^`\n]+`"),
    re.compile(r"\[\d+(?:\s*[-,–]\s*\d+)*\]"),
]

_COMBINED = re.compile("|".join(f"(?:{pattern.pattern})" for pattern in _PROTECTED_PATTERNS), re.S)

# A trailing fragment that could still become a placeholder is held back until
# the next token, so the UI never shows half a marker.
_MAX_PLACEHOLDER = len(OPEN) + 4 + len(CLOSE)


@dataclass(frozen=True)
class Protected:
    """Masked text plus the exact spans removed from it."""

    masked: str
    items: list[str]


def protect(text: str) -> Protected:
    """Replace every protected span with ``⟦n⟧``, in reading order."""
    items: list[str] = []
    pieces: list[str] = []
    cursor = 0
    for match in _COMBINED.finditer(text):
        pieces.append(text[cursor : match.start()])
        pieces.append(f"{OPEN}{len(items)}{CLOSE}")
        items.append(match.group(0))
        cursor = match.end()
    pieces.append(text[cursor:])
    return Protected(masked="".join(pieces), items=items)


def restore(text: str, items: list[str]) -> str:
    """Put the protected spans back. An unknown index is left as written."""

    def _swap(match: re.Match[str]) -> str:
        index = int(match.group(1))
        return items[index] if 0 <= index < len(items) else match.group(0)

    return PLACEHOLDER_RE.sub(_swap, text)


def integrity(text: str, items: list[str]) -> tuple[list[int], list[int]]:
    """(missing, duplicated) placeholder indexes in a finished translation."""
    counts: dict[int, int] = {}
    for match in PLACEHOLDER_RE.finditer(text):
        index = int(match.group(1))
        counts[index] = counts.get(index, 0) + 1
    missing = [index for index in range(len(items)) if counts.get(index, 0) == 0]
    duplicated = [index for index in range(len(items)) if counts.get(index, 0) > 1]
    return missing, duplicated


def split_segments(text: str) -> list[tuple[str, bool]]:
    """Text split into (chunk, protected) pairs, in order.

    Consecutive prose between two protected spans stays together; the spans
    themselves are returned verbatim with ``protected=True``.
    """
    segments: list[tuple[str, bool]] = []
    cursor = 0
    for match in _COMBINED.finditer(text):
        if match.start() > cursor:
            segments.append((text[cursor : match.start()], False))
        segments.append((match.group(0), True))
        cursor = match.end()
    if cursor < len(text):
        segments.append((text[cursor:], False))
    return segments


def hold_point(text: str) -> int:
    """How much of a streaming buffer is safe to emit.

    A trailing ``⟦`` (or a partial index inside one) might still be completed
    by the next token; everything before it can go out immediately.
    """
    start = text.rfind(OPEN)
    if start == -1:
        return len(text)
    tail = text[start:]
    if PLACEHOLDER_RE.fullmatch(tail):
        return len(text)
    if len(tail) <= _MAX_PLACEHOLDER and CLOSE not in tail:
        return start
    return len(text)
