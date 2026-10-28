"""Reference verification against real bibliographic databases (T7.1).

H02 forbids inventing a reference. A title is `verified` only when an external
record actually matches it: normalised-title token containment >= 0.9 (short
titles must match exactly), and, when the caller knows the expected metadata, a
compatible year and one shared author. The evidence (DOI, arXiv id, URL) is
copied from the record; this module never builds a citation out of a template.

The four sources are queried in two stages. Crossref and OpenAlex cover most
published work; arXiv and Semantic Scholar are only asked when the first stage
produced no title match, which keeps a twenty-title batch quick.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from ..discover.http import SafeClient, get_client
from ..discover.sources import (
    Candidate,
    arxiv,
    crossref,
    normalize_title,
    openalex,
    semantic_scholar,
)

logger = logging.getLogger(__name__)

VERIFY_MIN = 0.9
MAX_TITLES = 20
SHORT_TITLE_TOKENS = 3

Adapter = Callable[[str, SafeClient, int], Awaitable[list[Candidate]]]
PRIMARY: tuple[Adapter, ...] = (crossref, openalex)
FALLBACK: tuple[Adapter, ...] = (arxiv, semantic_scholar)

_DOI_PREFIX = re.compile(r"^10\.\d{4,9}/\S+$")


def title_tokens(title: str) -> set[str]:
    return set(normalize_title(title).split())


def title_similarity(left: str, right: str) -> float:
    """Share of the shorter title's tokens present in the other.

    Either-containment handles a subtitle or venue suffix on one side; titles
    with fewer than three tokens only match when they are equal, so "BERT"
    cannot confirm every paper that mentions BERT.
    """
    first, second = title_tokens(left), title_tokens(right)
    if not first or not second:
        return 0.0
    if min(len(first), len(second)) < SHORT_TITLE_TOKENS:
        return 1.0 if first == second else 0.0
    shared = len(first & second)
    if shared == 0:
        return 0.0
    return max(shared / len(first), shared / len(second))


def _surnames(authors: Sequence[str]) -> set[str]:
    names: set[str] = set()
    for author in authors:
        cleaned = re.sub(r"[^0-9A-Za-z一-鿿]+", " ", author).strip().lower()
        if not cleaned or cleaned in {"et al", "others"}:
            continue
        names.add(cleaned.split()[-1])
    return names


def authors_overlap(left: Sequence[str], right: Sequence[str]) -> bool:
    """True when neither side is known, or when one surname is shared."""
    first, second = _surnames(left), _surnames(right)
    if not first or not second:
        return True
    return bool(first & second)


def year_compatible(expected: int | None, found: int | None) -> bool:
    return expected is None or found is None or expected == found


def source_url(candidate: Candidate) -> str | None:
    """A real link from the record, preferring the canonical identifier."""
    if candidate.doi and _DOI_PREFIX.match(candidate.doi):
        return f"https://doi.org/{candidate.doi}"
    if candidate.arxiv_id:
        return f"https://arxiv.org/abs/{candidate.arxiv_id}"
    if candidate.url and candidate.url.startswith(("https://", "http://")):
        return candidate.url
    return None


def best_match(
    title: str,
    candidates: Sequence[Candidate],
    *,
    year: int | None = None,
    authors: Sequence[str] = (),
) -> tuple[Candidate, float] | None:
    """The highest-scoring record that clears every gate, or None."""
    scored: list[tuple[float, int, int, int, Candidate]] = []
    for candidate in candidates:
        similarity = title_similarity(title, candidate.title)
        if similarity < VERIFY_MIN:
            continue
        if not year_compatible(year, candidate.year):
            continue
        if not authors_overlap(authors, candidate.authors):
            continue
        scored.append(
            (
                similarity,
                int(candidate.doi is not None),
                int(candidate.arxiv_id is not None),
                candidate.year or 0,
                candidate,
            )
        )
    if not scored:
        return None
    best = max(scored, key=lambda item: item[:4])
    return best[4], best[0]


async def _from_adapters(
    adapters: Sequence[Adapter], title: str, client: SafeClient, limit: int = 5
) -> list[Candidate]:
    found: list[Candidate] = []
    for adapter in adapters:
        try:
            found.extend(await adapter(title, client, limit))
        except Exception as exc:  # a failed source must not fail the check
            logger.warning("verify: %s failed for %r: %s", adapter.__name__, title, exc)
    return found


async def lookup_title(title: str, client: SafeClient | None = None) -> list[Candidate]:
    """Search the four sources for a title, stopping early on a clear match."""
    client = client or get_client()
    pool = await _from_adapters(PRIMARY, title, client)
    if best_match(title, pool) is None:
        pool = [*pool, *await _from_adapters(FALLBACK, title, client)]
    return pool


async def verify_title(
    title: str,
    client: SafeClient | None = None,
    *,
    year: int | None = None,
    authors: Sequence[str] = (),
) -> tuple[Candidate, float] | None:
    pool = await lookup_title(title, client)
    return best_match(title, pool, year=year, authors=authors)


def _check_row(title: str, match: tuple[Candidate, float] | None) -> dict[str, Any]:
    if match is None:
        return {"title": title, "status": "unverified", "source_url": None, "arxiv_id": None, "doi": None}
    found, _similarity = match
    return {
        "title": title,
        "status": "verified",
        "source_url": source_url(found),
        "arxiv_id": found.arxiv_id,
        "doi": found.doi,
    }


async def verify_titles(titles: Sequence[str], client: SafeClient | None = None) -> list[dict[str, Any]]:
    """Verify up to ``MAX_TITLES`` titles, preserving the input order.

    An unreachable database yields `unverified`, not an exception: "we could
    not check" must never be reported as "real".
    """
    client = client or get_client()
    rows: list[dict[str, Any]] = []
    for title in list(titles)[:MAX_TITLES]:
        match = await verify_title(title, client)
        rows.append(_check_row(title, match))
    return rows
