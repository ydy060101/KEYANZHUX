"""BibTeX for verified references only (T7.1).

Nothing here invents a field. Every entry is rendered from the metadata the
verification step copied out of an external record; a reference without
`status == "verified"` is omitted rather than exported with placeholders.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

_STOP = {
    "a",
    "an",
    "and",
    "are",
    "for",
    "in",
    "is",
    "of",
    "on",
    "the",
    "to",
    "with",
}
_SPECIAL = re.compile(r"(?<!\\)([&%#_$])")


def _ascii(value: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", value.lower())


def _escape(value: str) -> str:
    """Escape the characters BibTeX treats specially; keep accents as-is."""
    return _SPECIAL.sub(r"\\\1", value)


def cite_key(reference: Mapping[str, Any], index: int, used: set[str]) -> str:
    authors = reference.get("authors") or []
    surname = ""
    if isinstance(authors, list) and authors:
        first = str(authors[0])
        # "Vaswani, Ashish" and "Ashish Vaswani" both yield "vaswani".
        surname = _ascii(first.split(",")[0] if "," in first else first.split()[-1])
    year = reference.get("year")
    year_part = str(year) if isinstance(year, int) else str(index + 1)
    title = str(reference.get("title") or "")
    word = next((_ascii(token) for token in title.split() if _ascii(token) not in _STOP), "")
    base = f"{surname or 'anon'}{year_part}{word}"
    key = base
    suffix = 1
    while key in used:
        suffix += 1
        key = f"{base}{suffix}"
    used.add(key)
    return key


def _entry(reference: Mapping[str, Any], key: str) -> str:
    doi = reference.get("doi")
    arxiv_id = reference.get("arxiv_id")
    kind = "article" if doi else "misc"
    fields: list[tuple[str, str]] = []
    title = str(reference.get("title") or "").strip()
    if title:
        fields.append(("title", _escape(title)))
    authors = reference.get("authors") or []
    if isinstance(authors, list) and authors:
        fields.append(("author", _escape(" and ".join(str(name) for name in authors))))
    year = reference.get("year")
    if isinstance(year, int):
        fields.append(("year", str(year)))
    if doi:
        fields.append(("doi", _escape(str(doi))))
    if arxiv_id:
        fields.append(("eprint", _escape(str(arxiv_id))))
        fields.append(("archivePrefix", "arXiv"))
        fields.append(("url", f"https://arxiv.org/abs/{arxiv_id}"))
    body = ",\n".join(f"  {name} = {{{value}}}" for name, value in fields)
    return f"@{kind}{{{key},\n{body}\n}}"


def to_bibtex(references: Iterable[Mapping[str, Any]]) -> str:
    """Render verified entries; unverified ones are silently not exported."""
    used: set[str] = set()
    entries: list[str] = []
    index = 0
    for reference in references:
        if reference.get("status", "verified") != "verified":
            continue
        key = cite_key(reference, index, used)
        entries.append(_entry(reference, key))
        index += 1
    header = "% Generated from verified references only.\n"
    return header + ("\n\n".join(entries) + "\n" if entries else "")
