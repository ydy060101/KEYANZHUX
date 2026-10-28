"""Outline generation pipeline (T7.1).

Plan → real search → verification → prose → persist. The model never supplies
a reference on its own: candidates come from `discover.search` and must pass
`verify.py` before the draft may cite them. `citations.py` repairs the keys the
provider actually writes and drops anything it cannot map to a verified record.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..discover.http import SafeClient, get_client
from ..discover.sources import Candidate, normalize_title, search
from ..llm.errors import LLMError
from ..llm.gateway import get_gateway
from ..llm.safety import system_with_guard, wrap_data
from ..llm.types import ChatResult
from ..models.orm import Draft
from .bibtex import cite_key, to_bibtex
from .citations import assemble, claim_flags
from .prompts import (
    HEADINGS,
    MAX_IDEA,
    MAX_QUERIES,
    OutlineDraft,
    OutlineInput,
    OutlinePlan,
    SectionDraft,
    SectionPlan,
    draft_messages,
    plan_messages,
)
from .verify import verify_title

logger = logging.getLogger(__name__)

MAX_CANDIDATES = 7
MAX_REFS = 6

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]

# Function words would let an unrelated paper ride on "of" or "for".
_CONTEXT_STOP = {
    "a",
    "an",
    "and",
    "for",
    "from",
    "in",
    "of",
    "on",
    "the",
    "to",
    "using",
    "via",
    "with",
}


def _clean_query(value: str) -> str:
    return " ".join(value.split())[:200].strip()


def _usable(plan: OutlinePlan) -> bool:
    """The provider often leaves the optional query fields empty; a single
    English phrase is enough, Chinese queries cannot drive these databases."""
    values = [*plan.queries, *(query for section in plan.sections for query in section.queries)]
    return any(re.search(r"[A-Za-z]{2,}", query or "") for query in values)


async def derive_queries(gateway: Any, idea: str) -> list[str]:
    """One plain-text call, because the JSON plan's query fields go unfilled."""
    messages = [
        {
            "role": "system",
            "content": system_with_guard(
                "You produce bibliographic search queries. Return three short English keyword "
                "queries, one per line, no numbering and no explanation. Never invent a paper title."
            ),
        },
        {"role": "user", "content": f"Research idea:\n{wrap_data(idea)}"},
    ]
    result = await gateway.chat(messages, tier="fast", temperature=0.0, cache_prefix="writing:queries:v1")
    if not isinstance(result, ChatResult):
        return []
    found: list[str] = []
    seen: set[str] = set()
    for raw in result.text.splitlines():
        query = re.sub(r"^\s*(?:[-*•]|\d+[.)、])\s*", "", raw).strip()
        if not 2 <= len(query.split()) <= 12 or not re.search(r"[A-Za-z]{2,}", query):
            continue
        if query.casefold() in seen:
            continue
        seen.add(query.casefold())
        found.append(query)
        if len(found) == 3:
            break
    return found


def _queries(plan: OutlinePlan, idea: str) -> list[str]:
    raw = [*plan.queries, *(query for section in plan.sections for query in section.queries)]
    seen: set[str] = set()
    out: list[str] = []
    for value in raw:
        query = _clean_query(str(value))
        if not query or query.casefold() in seen:
            continue
        seen.add(query.casefold())
        out.append(query)
        if len(out) == MAX_QUERIES:
            break
    if not out:
        out = [_clean_query(idea)[:200] or "recent research"]
    english = [query for query in out if re.search(r"[A-Za-z]{2,}", query)]
    return english or out[:1]


def _relevance(candidate: Candidate, context: set[str]) -> float:
    tokens = set(normalize_title(candidate.title).split())
    if not tokens:
        return 0.0
    return len(tokens & context) / len(tokens)


def _shared(candidate: Candidate, context: set[str]) -> int:
    return len(set(normalize_title(candidate.title).split()) & context)


async def search_candidates(plan: OutlinePlan, idea: str, client: SafeClient | None = None) -> list[Candidate]:
    """Real search results only; failures from one query do not stop the rest."""
    client = client or get_client()
    queries = _queries(plan, idea)
    results = await asyncio.gather(*(search(query, client, limit=5) for query in queries), return_exceptions=True)
    found: list[Candidate] = []
    for result in results:
        if isinstance(result, BaseException):
            logger.warning("outline: search failed: %s", result)
            continue
        found.extend(result[0])
    context = set(normalize_title(f"{idea} {' '.join(queries)}").split()) - _CONTEXT_STOP

    unique: dict[str, Candidate] = {}
    for candidate in found:
        key = candidate.arxiv_id or (candidate.doi or "").lower() or normalize_title(candidate.title)
        if not key:
            continue
        existing = unique.get(key)
        if existing is None or (candidate.doi is not None and existing.doi is None):
            unique[key] = candidate
    ranked = sorted(
        unique.values(),
        key=lambda item: (
            -_relevance(item, context),
            -int(item.doi is not None or item.arxiv_id is not None),
            normalize_title(item.title),
        ),
    )
    # A real bibliography entry that shares only "survey" with the topic is
    # noise, even though it verifies. Two shared content tokens or nothing.
    focused = [candidate for candidate in ranked if _shared(candidate, context) >= 2]
    logger.info(
        "outline: %d queries, %d raw candidates, %d unique, %d focused",
        len(queries),
        len(found),
        len(unique),
        len(focused),
    )
    return focused[:MAX_CANDIDATES]


async def _verify_one(candidate: Candidate, client: SafeClient) -> tuple[Candidate, float] | None:
    try:
        match = await verify_title(candidate.title, client, year=candidate.year, authors=candidate.authors)
    except Exception as exc:  # verification failure means "not confirmed"
        logger.warning("outline: verification failed for %r: %s", candidate.title, exc)
        return None
    if match is None:
        return None
    found, similarity = match
    return found, similarity


async def verify_candidates(candidates: Sequence[Candidate], client: SafeClient | None = None) -> list[dict[str, Any]]:
    """Keep only candidates a database confirms; assign stable citation keys."""
    client = client or get_client()
    matches = await asyncio.gather(*(_verify_one(candidate, client) for candidate in candidates))
    verified: list[dict[str, Any]] = []
    seen: set[str] = set()
    used: set[str] = set()
    for match in matches:
        if match is None:
            continue
        found, similarity = match
        key = found.arxiv_id or (found.doi or "").lower() or normalize_title(found.title)
        if not key or key in seen:
            continue
        seen.add(key)
        reference = {
            "title": found.title,
            "authors": list(found.authors),
            "year": found.year,
            "doi": found.doi,
            "arxiv_id": found.arxiv_id,
            "source_url": _url(found),
            "status": "verified",
            "similarity": round(similarity, 4),
        }
        reference["key"] = cite_key(reference, len(verified), used)
        verified.append(reference)
        if len(verified) == MAX_REFS:
            break
    return verified


def _url(candidate: Candidate) -> str | None:
    if candidate.doi and candidate.doi.startswith("10."):
        return f"https://doi.org/{candidate.doi}"
    if candidate.arxiv_id:
        return f"https://arxiv.org/abs/{candidate.arxiv_id}"
    if candidate.url and candidate.url.startswith(("https://", "http://")):
        return candidate.url
    return None


async def generate_outline(session: AsyncSession, body: OutlineInput, emit: Emit) -> None:
    """Plan → search → verify → write → persist, reporting each stage."""
    gateway = get_gateway()
    await emit("stage", {"stage": "planning", "message": "正在生成框架结构"})
    plan = await gateway.chat_json(
        plan_messages(body.idea, body.language, body.venue),
        OutlinePlan,
        tier="strong",
        temperature=0.0,
        cache_prefix=f"writing:plan:v1:{body.language}",
    )
    if not plan.sections:
        plan.sections = [SectionPlan(heading=heading) for heading in HEADINGS]

    await emit("stage", {"stage": "searching", "message": "正在检索候选文献"})
    if not _usable(plan):
        try:
            plan.queries = await derive_queries(gateway, body.idea)
        except LLMError as exc:
            logger.warning("outline: query generation failed: %s", exc)
    candidates = await search_candidates(plan, body.idea)
    await emit(
        "stage",
        {"stage": "verifying", "message": f"正在核验 {len(candidates)} 篇候选文献", "count": len(candidates)},
    )
    references = await verify_candidates(candidates) if candidates else []

    await emit("stage", {"stage": "writing", "message": "正在撰写框架正文"})
    draft = await gateway.chat_json(
        draft_messages(body.idea, body.language, body.venue, plan, references),
        OutlineDraft,
        tier="strong",
        temperature=0.0,
        cache_prefix=f"writing:draft:v1:{body.language}",
    )
    markdown, sections = assemble(draft, plan, references)
    flags = claim_flags(sections)
    missing = markdown.count("[待补充]")
    if missing:
        flags.append(
            {
                "kind": "missing_reference",
                "section": "",
                "text": f"框架中有 {missing} 处标记为 [待补充]，需人工补充",
            }
        )

    row = Draft(
        idea=body.idea,
        outline={
            "title": markdown.splitlines()[0].lstrip("# ").strip(),
            "markdown": markdown,
            "sections": sections,
            "language": body.language,
            "venue": body.venue,
            "flags": flags,
        },
        references={"items": references},
        bibtex=to_bibtex(references),
    )
    session.add(row)
    await session.commit()

    await emit(
        "done",
        {
            "draft_id": row.id,
            "outline": row.outline,
            "references": references,
            "bibtex": row.bibtex,
            "flags": flags,
        },
    )


__all__ = [
    "HEADINGS",
    "MAX_IDEA",
    "OutlineDraft",
    "OutlineInput",
    "OutlinePlan",
    "SectionDraft",
    "SectionPlan",
    "assemble",
    "claim_flags",
    "generate_outline",
    "search_candidates",
    "verify_candidates",
]
