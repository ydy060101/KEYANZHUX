"""Figure captions grounded in computed statistics (T7.3).

The model drafts one caption, then every number in it is checked against the
`stats` JSON. A caption that names a value the data does not contain is
discarded and the deterministic template replaces it (H02/H04): a chart caption
is a claim about the data, so it may not carry an invented number.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field

from ..llm.errors import LLMError
from ..llm.safety import system_with_guard, wrap_data

logger = logging.getLogger(__name__)

MAX_CAPTION_CHARS = 800
_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")
_REFERENCE = re.compile(r"(?:figure|fig\.?|table|图|表)\s*\d+", re.IGNORECASE)
_PREFIX = re.compile(r"^\s*(?:figure|fig\.?|table|图|表)\s*\d+\s*[.:：\-—]?\s*", re.IGNORECASE)
_FENCE = re.compile(r"^```(?:\w+)?\s*|\s*```$", re.IGNORECASE)


class CaptionDraft(BaseModel):
    caption: str = Field(default="", max_length=MAX_CAPTION_CHARS)
    caption_zh: str = Field(default="", max_length=MAX_CAPTION_CHARS)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _variants(number: float) -> set[float]:
    """Every rounding a caption may legitimately use, plus the percentage form."""
    out: set[float] = set()
    for value in (number, abs(number), number * 100, abs(number) * 100):
        for digits in range(5):
            out.add(round(value, digits))
    return out


def allowed_numbers(stats: dict[str, Any]) -> set[float]:
    out: set[float] = set()

    def collect(value: Any) -> None:
        if _is_number(value):
            out.update(_variants(float(value)))
        elif isinstance(value, str):
            stripped = value.strip()
            # Category labels ("Q4", "fold-5") may appear in a caption; every
            # numeral in a stats string is part of the data's own vocabulary.
            for match in _NUMBER.finditer(stripped):
                out.update(_variants(float(match.group())))
        elif isinstance(value, dict):
            for item in value.values():
                collect(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                collect(item)

    collect(stats)
    return out


def _numbers(text: str) -> list[float]:
    visible = _REFERENCE.sub(" ", _PREFIX.sub("", text))
    return [float(match.group()) for match in _NUMBER.finditer(visible)]


def grounded(text: str, allowed: set[float]) -> bool:
    """True when every number in `text` comes from the stats."""
    return all(any(abs(value - candidate) <= 1e-9 for candidate in allowed) for value in _numbers(text))


def _prefix(kind: str, language: str) -> str:
    if language == "zh":
        return "表 1." if kind == "table" else "图 1."
    return "Table 1." if kind == "table" else "Figure 1."


def normalize_caption(text: str, kind: str, language: str) -> str:
    cleaned = _FENCE.sub("", text).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    body = _PREFIX.sub("", cleaned).strip()
    if not body:
        return ""
    return f"{_prefix(kind, language)} {body}"


def _fmt(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    number = float(value)
    if number == 0:
        return "0"
    if abs(number) >= 1000:
        return f"{number:.1f}"
    if abs(number) >= 1:
        return f"{number:.2f}".rstrip("0").rstrip(".")
    return f"{number:.6f}".rstrip("0").rstrip(".")


def fallback_caption(stats: dict[str, Any], kind: str, x: str, ys: Sequence[str]) -> tuple[str, str]:
    """Deterministic, all values copied from `stats`."""
    en = [f"{_prefix(kind, 'en')} {x} against {', '.join(ys)}."]
    zh = [f"{_prefix(kind, 'zh')} {x} 与 {', '.join(ys)} 的统计概览。"]
    for name in ys:
        series = stats.get("series", {}).get(name) or {}
        if not series.get("numeric"):
            count = series.get("n", 0)
            en.append(f"{name} has {count} non-empty values.")
            zh.append(f"{name} 有 {count} 个非空值。")
            continue
        low, high = series.get("min"), series.get("max")
        mean = series.get("mean")
        peak_x = series.get("peak_x")
        en.append(f"{name} ranges from {_fmt(low)} to {_fmt(high)}, mean {_fmt(mean)}, peaking at {peak_x}.")
        zh.append(f"{name} 的范围为 {_fmt(low)}–{_fmt(high)}，均值 {_fmt(mean)}，峰值出现在 {peak_x}。")
    if stats.get("normalized"):
        en.append("Values are min-max normalized per series.")
        zh.append("各序列按最小值—最大值归一化。")
    return " ".join(en), "".join(zh)


def caption_messages(stats: dict[str, Any], kind: str, x: str, ys: Sequence[str]) -> list[dict[str, str]]:
    system = system_with_guard(
        "You write one academic figure caption. Return JSON with exactly two keys: "
        "caption (English) and caption_zh (Simplified Chinese). "
        "Use only numbers that appear in the statistics JSON: do not compute, round "
        "to a new value, or add any metric that is absent. Never claim significance, "
        "causality or a finding the statistics do not contain. Do not start with "
        "'Figure 1' or 'Table 1'; the caller adds that label."
    )
    payload = json.dumps(stats, ensure_ascii=False, indent=2)
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": (
                f"Chart type: {kind}\nX axis: {x}\nY series: {', '.join(ys)}\n\nStatistics:\n{wrap_data(payload)}"
            ),
        },
    ]


async def make_caption(gateway: Any, stats: dict[str, Any], kind: str, x: str, ys: Sequence[str]) -> tuple[str, str]:
    """Model caption if every number checks out, else the deterministic one."""
    allowed = allowed_numbers(stats)
    try:
        draft = await gateway.chat_json(
            caption_messages(stats, kind, x, ys),
            CaptionDraft,
            tier="fast",
            temperature=0.0,
            cache_prefix="writing:data:caption:v1",
        )
    except LLMError as exc:
        logger.warning("chart caption: LLM unavailable, using fallback: %s", exc)
        return fallback_caption(stats, kind, x, ys)

    caption = normalize_caption(draft.caption, kind, "en")
    caption_zh = normalize_caption(draft.caption_zh, kind, "zh")
    if caption and grounded(caption, allowed) and (not caption_zh or grounded(caption_zh, allowed)):
        return caption, caption_zh
    logger.warning("chart caption rejected: a number is not present in stats")
    return fallback_caption(stats, kind, x, ys)


__all__ = [
    "allowed_numbers",
    "caption_messages",
    "fallback_caption",
    "grounded",
    "make_caption",
    "normalize_caption",
]
