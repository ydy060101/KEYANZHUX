"""Recommendations built from the reader's own library (T5.6).

The feed is deliberately simple and auditable: take the most recently added
titles, search arXiv with each, drop anything already owned, and score a hit by
the share of the seed title's keywords it repeats. Every reason names the seed
and the shared keywords, so a reader can see why a paper was shown (H02); the
score is a number, not a model's opinion.

A source failure empties that seed's contribution but not the feed; with no
usable seeds the feed is empty and the UI says so (H08).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.orm import Document
from .http import SafeClient
from .sources import arxiv, normalize_title

logger = logging.getLogger(__name__)

SEEDS = 3
PER_SEED = 8
MIN_SEED_TOKENS = 2

_STOP = {
    "and", "are", "all", "based", "can", "for", "from", "into", "its", "new",
    "not", "our", "that", "the", "their", "this", "toward", "towards", "using",
    "via", "with", "you", "your",
}


def title_tokens(title: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9]+", title.lower())
        if len(word) >= 3 and word not in _STOP
    }


def _query(title: str) -> str:
    """The title as an arXiv phrase query: quotes would end the phrase."""
    return " ".join(title.replace('"', " ").split())[:200]


async def recommend(
    session: AsyncSession, user: str, client: SafeClient, limit: int
) -> list[dict[str, Any]]:
    docs = (
        (
            await session.execute(
                select(Document)
                .where(Document.created_by == user, Document.title != "")
                .order_by(Document.created_at.desc())
                .limit(SEEDS * 4)
            )
        )
        .scalars()
        .all()
    )
    seeds = [doc for doc in docs if len(title_tokens(doc.title)) >= MIN_SEED_TOKENS][:SEEDS]
    if not seeds:
        return []

    owned = (
        await session.execute(
            select(Document.arxiv_id, Document.title).where(Document.created_by == user)
        )
    ).all()
    library_arxiv = {row.arxiv_id for row in owned if row.arxiv_id}
    library_titles = {normalize_title(row.title or "") for row in owned}

    results = await asyncio.gather(
        *(arxiv(_query(seed.title), client, PER_SEED) for seed in seeds),
        return_exceptions=True,
    )

    best: dict[str, dict[str, Any]] = {}
    for seed, found in zip(seeds, results, strict=True):
        if isinstance(found, BaseException):
            logger.warning("recommend seed %r failed: %s", seed.title, found)
            continue
        seed_tokens = title_tokens(seed.title)
        for candidate in found:
            if candidate.arxiv_id and candidate.arxiv_id in library_arxiv:
                continue
            if normalize_title(candidate.title) in library_titles:
                continue
            shared = seed_tokens & title_tokens(candidate.title)
            score = round(len(shared) / len(seed_tokens), 3)
            reasons = [
                f"与库内《{seed.title}》共享关键词：{'、'.join(sorted(shared)[:4])}"
                if shared
                else f"由库内《{seed.title}》的标题检索得到"
            ]
            if candidate.year:
                reasons.append(f"arXiv {candidate.year}")
            key = candidate.arxiv_id or normalize_title(candidate.title)
            row = {
                "paper_id": candidate.ext_id,
                "title": candidate.title,
                "authors": candidate.authors,
                "year": candidate.year,
                "score": score,
                "reasons": reasons,
                "github_url": candidate.github_url,
                "stars": candidate.stars,
                # Additive fields: the UI needs these to import the hit.
                "source": candidate.source,
                "abstract": candidate.abstract,
                "pdf_url": candidate.pdf_url,
            }
            previous = best.get(key)
            if previous is None or row["score"] > previous["score"]:
                best[key] = row

    ordered = sorted(
        best.values(),
        key=lambda row: (-row["score"], -(row["year"] or 0), row["title"]),
    )
    return ordered[:limit]
