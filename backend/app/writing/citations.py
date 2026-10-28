"""Citation-key repair, outline assembly and claim flags (T7.1).

The provider does not reliably echo the opaque keys it is given: it writes
author-year keys and sometimes drops the braces. `_resolve` accepts such a key
only when it points at exactly one verified reference; everything else becomes
`[待补充]`, so a hallucinated citation cannot reach the draft or the BibTeX.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from .prompts import HEADINGS, OutlineDraft, OutlinePlan

_KEY_CHARS = r"A-Za-z0-9{}_:\-"
_CITE = re.compile(rf"\\cite\{{?([{_KEY_CHARS}]+(?:,[{_KEY_CHARS}]+)*)\}}?")
_FENCE = re.compile(r"^```(?:markdown|md)?\s*|\s*```$", re.IGNORECASE)
_KEY_WORD = re.compile(r"[a-z]{3,}")

_HEADING_ALIASES = {
    "abstract": "Abstract",
    "摘要": "Abstract",
    "introduction": "Introduction",
    "引言": "Introduction",
    "介绍": "Introduction",
    "related work": "Related Work",
    "related works": "Related Work",
    "相关工作": "Related Work",
    "相关研究": "Related Work",
}

_CLAIM = re.compile(
    r"(实验(?:表明|显示|结果)|结果表明|测试结果|"
    r"results? (?:show|demonstrate)|experiments? (?:show|demonstrate)|"
    r"we (?:find|found|observed)|outperform(?:s|ed)?)",
    re.IGNORECASE,
)


def _alnum(value: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", value.casefold())


def _key_parts(reference: dict[str, Any]) -> tuple[str, int | None, set[str]]:
    authors = reference.get("authors") or []
    surname = ""
    if isinstance(authors, list) and authors:
        first = str(authors[0])
        surname = _alnum(first.split(",")[0] if "," in first else first.split()[-1])
    year = reference.get("year")
    words = {_alnum(token) for token in str(reference.get("title") or "").split()}
    return surname, year if isinstance(year, int) else None, {word for word in words if len(word) >= 3}


def _resolve(raw: str, references: Sequence[dict[str, Any]]) -> str | None:
    """Map a model-written key to one verified reference, or nothing."""
    raw = raw.strip()
    cleaned = _alnum(raw)
    for reference in references:
        key = str(reference.get("key"))
        if key == raw or (cleaned and _alnum(key) == cleaned):
            return key
    if not cleaned:
        return None
    words = set(_KEY_WORD.findall(cleaned))
    scored: list[tuple[int, str]] = []
    for reference in references:
        surname, year, title_words = _key_parts(reference)
        score = 0
        if surname and cleaned.startswith(surname):
            score += 2
        if year is not None and str(year) in cleaned:
            score += 1
        if words & title_words:
            score += 1
        if score >= 3:
            scored.append((score, str(reference.get("key"))))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][1]


def _apply_citations(text: str, references: Sequence[dict[str, Any]]) -> str:
    def replace(match: re.Match[str]) -> str:
        kept: list[str] = []
        for part in re.split(r"[,;\s]+", match.group(1)):
            key = _resolve(part, references)
            if key is not None and key not in kept:
                kept.append(key)
        return "\\cite{" + ",".join(kept) + "}" if kept else "[待补充]"

    return _CITE.sub(replace, text)


def _heading(raw: str) -> str | None:
    cleaned = re.sub(r"^[#*\s]+|\*+$", "", raw).strip().rstrip(":").strip()
    cleaned = re.sub(r"^\d+(?:\.\d+)*[.)、\s]+", "", cleaned)
    key = cleaned.casefold()
    if key in _HEADING_ALIASES:
        return _HEADING_ALIASES[key]
    for alias, heading in _HEADING_ALIASES.items():
        if alias in key:
            return heading
    return None


def assemble(
    draft: OutlineDraft, plan: OutlinePlan, references: Sequence[dict[str, Any]]
) -> tuple[str, list[dict[str, str]]]:
    """Canonical three sections, citations filtered, missing prose marked."""

    def body(raw: str) -> str:
        cleaned = _FENCE.sub("", raw).strip()
        cleaned = re.sub(r"^#{1,6}\s+[^\n]*\n+", "", cleaned)
        return _apply_citations(cleaned, references) or "[待补充]"

    by_heading: dict[str, str] = {}
    for section in draft.sections:
        heading = _heading(section.heading)
        if heading is None or heading in by_heading:
            continue
        by_heading[heading] = body(section.markdown)
    named = {
        "Abstract": draft.abstract,
        "Introduction": draft.introduction,
        "Related Work": draft.related_work,
    }
    for heading, text in named.items():
        if text.strip():
            by_heading[heading] = body(text)
    sections: list[dict[str, str]] = [
        {"heading": heading, "markdown": by_heading.get(heading, "[待补充]")} for heading in HEADINGS
    ]
    title = draft.title.strip() or plan.title.strip() or "Untitled outline"
    lines = [f"# {title}", ""]
    for item in sections:
        lines.extend([f"## {item['heading']}", "", item["markdown"], ""])
    return "\n".join(lines).rstrip() + "\n", sections


def claim_flags(sections: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    """An outline is a plan; a result sentence is unverified by construction."""
    flags: list[dict[str, str]] = []
    for section in sections:
        if _CLAIM.search(section["markdown"]):
            flags.append(
                {
                    "kind": "unverified_claim",
                    "section": section["heading"],
                    "text": f"{section['heading']} 含实验结论式表述，需在真实实验后核实",
                }
            )
    return flags


__all__ = ["assemble", "claim_flags"]
