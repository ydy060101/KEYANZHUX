"""The four academic sources behind `/discover/search` (T5.1).

arXiv is the primary source because its PDFs are directly downloadable and
its identifiers are stable. Semantic Scholar, OpenAlex and Crossref add
metadata, DOI links and abstracts; the merge prefers an arXiv record when the
same paper appears in several sources.

Each adapter returns :class:`Candidate` values and never raises for a source
failure — the caller collects `sources[source] = "ok" | "error: …"` and shows
the degraded result (H08). Parsing is defensive: a field the provider renamed
or omitted becomes `None`, never an invented value (H02).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from typing import Any

from .http import SafeClient, safe_pdf_url

logger = logging.getLogger(__name__)

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_QUERY = "https://export.arxiv.org/api/query"
S2_SEARCH = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_PAPER = "https://api.semanticscholar.org/graph/v1/paper"
OPENALEX = "https://api.openalex.org/works"
CROSSREF = "https://api.crossref.org/works"

SOURCES = ("arxiv", "semanticscholar", "openalex", "crossref")


@dataclass
class Candidate:
    source: str
    ext_id: str
    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    abstract: str | None = None
    pdf_url: str | None = None
    url: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    github_url: str | None = None
    stars: int | None = None
    in_library: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def _text(node: ET.Element | None) -> str | None:
    if node is None or node.text is None:
        return None
    value = " ".join(node.text.split())
    return value or None


def _year(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        match = re.search(r"(19|20)\d{2}", value)
        return int(match.group(0)) if match else None
    return None


def _arxiv_id(raw: str | None) -> str | None:
    if not raw:
        return None
    match = re.search(r"(\d{4}\.\d{4,5})(v\d+)?", raw)
    return match.group(1) if match else None


async def arxiv(query: str, client: SafeClient, limit: int = 10) -> list[Candidate]:
    body = await client.get(
        ARXIV_QUERY,
        source="arxiv",
        params={
            "search_query": f'all:"{query}"',
            "start": 0,
            "max_results": limit,
            "sortBy": "relevance",
        },
    )
    root = ET.fromstring(body)
    out: list[Candidate] = []
    for entry in root.findall(f"{ATOM}entry"):
        raw_id = _text(entry.find(f"{ATOM}id")) or ""
        ext_id = _arxiv_id(raw_id)
        if not ext_id:
            continue
        pdf_url = None
        for link in entry.findall(f"{ATOM}link"):
            if link.get("title") == "pdf" or link.get("type") == "application/pdf":
                pdf_url = link.get("href")
        out.append(
            Candidate(
                source="arxiv",
                ext_id=ext_id,
                arxiv_id=ext_id,
                title=_text(entry.find(f"{ATOM}title")) or ext_id,
                authors=[
                    name
                    for author in entry.findall(f"{ATOM}author")
                    if (name := _text(author.find(f"{ATOM}name")))
                ],
                year=_year(_text(entry.find(f"{ATOM}published"))),
                abstract=_text(entry.find(f"{ATOM}summary")),
                pdf_url=pdf_url or f"https://arxiv.org/pdf/{ext_id}",
                url=f"https://arxiv.org/abs/{ext_id}",
            )
        )
    return out


async def semantic_scholar(query: str, client: SafeClient, limit: int = 10) -> list[Candidate]:
    body = await client.get(
        S2_SEARCH,
        source="semanticscholar",
        params={
            "query": query,
            "limit": limit,
            "fields": "title,authors,year,abstract,externalIds,openAccessPdf,url",
        },
    )
    payload: dict[str, Any] = json.loads(body)
    out: list[Candidate] = []
    for item in payload.get("data") or []:
        title = item.get("title")
        if not title:
            continue
        external = item.get("externalIds") or {}
        open_pdf = item.get("openAccessPdf") or {}
        out.append(
            Candidate(
                source="semanticscholar",
                ext_id=str(item.get("paperId") or ""),
                title=title,
                authors=[a.get("name", "") for a in item.get("authors") or [] if a.get("name")],
                year=_year(item.get("year")),
                abstract=item.get("abstract"),
                pdf_url=open_pdf.get("url"),
                url=item.get("url"),
                doi=external.get("DOI"),
                arxiv_id=external.get("ArXiv"),
            )
        )
    return [candidate for candidate in out if candidate.ext_id]


async def openalex(query: str, client: SafeClient, limit: int = 10) -> list[Candidate]:
    body = await client.get(
        OPENALEX,
        source="openalex",
        params={"search": query, "per-page": limit, "mailto": "research-agent@example.org"},
    )
    payload: dict[str, Any] = json.loads(body)
    out: list[Candidate] = []
    for item in payload.get("results") or []:
        title = item.get("title") or item.get("display_name")
        if not title:
            continue
        location = item.get("primary_location") or {}
        open_access = item.get("open_access") or {}
        out.append(
            Candidate(
                source="openalex",
                ext_id=str(item.get("id") or "").rsplit("/", 1)[-1],
                title=title,
                authors=[
                    name
                    for authorship in item.get("authorships") or []
                    if (name := (authorship.get("author") or {}).get("display_name"))
                ],
                year=_year(item.get("publication_year")),
                abstract=_inverted_abstract(item.get("abstract_inverted_index")),
                pdf_url=open_access.get("oa_url") or location.get("pdf_url"),
                url=item.get("doi") or item.get("id"),
                doi=(item.get("doi") or "").replace("https://doi.org/", "") or None,
            )
        )
    return [candidate for candidate in out if candidate.ext_id]


async def crossref(query: str, client: SafeClient, limit: int = 10) -> list[Candidate]:
    body = await client.get(
        CROSSREF,
        source="crossref",
        params={"query.bibliographic": query, "rows": limit},
    )
    payload: dict[str, Any] = json.loads(body)
    items = (payload.get("message") or {}).get("items") or []
    out: list[Candidate] = []
    for item in items:
        titles = item.get("title") or []
        title = titles[0] if titles else None
        doi = item.get("DOI")
        if not title or not doi:
            continue
        issued = (item.get("issued") or {}).get("date-parts") or [[None]]
        year = _year(issued[0][0] if issued and issued[0] else None)
        out.append(
            Candidate(
                source="crossref",
                ext_id=str(doi),
                title=title,
                authors=[
                    " ".join(part for part in (a.get("given"), a.get("family")) if part)
                    for a in item.get("author") or []
                ],
                year=year,
                abstract=_strip_jats(item.get("abstract")),
                url=f"https://doi.org/{doi}",
                doi=str(doi),
            )
        )
    return out


def _inverted_abstract(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    positions: list[tuple[int, str]] = []
    for word, indexes in value.items():
        if isinstance(indexes, list):
            positions.extend((index, word) for index in indexes if isinstance(index, int))
    if not positions:
        return None
    return " ".join(word for _, word in sorted(positions))


def _strip_jats(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = re.sub(r"<[^>]+>", " ", value)
    text = " ".join(text.split())
    return text or None


def _dedupe(candidates: list[Candidate]) -> list[Candidate]:
    """One row per paper; an arXiv record wins, then one with a PDF."""
    best: dict[str, Candidate] = {}
    for candidate in candidates:
        keys = [key for key in (
            f"arxiv:{candidate.arxiv_id}" if candidate.arxiv_id else None,
            f"doi:{candidate.doi.lower()}" if candidate.doi else None,
            f"title:{normalize_title(candidate.title)}",
        ) if key]
        if not keys:
            continue
        existing = next((best[key] for key in keys if key in best), None)
        if existing is None:
            for key in keys:
                best[key] = candidate
            continue
        prefer = (
            candidate.source == "arxiv" and existing.source != "arxiv"
        ) or (candidate.pdf_url is not None and existing.pdf_url is None)
        if prefer:
            for key in keys:
                best[key] = candidate
            for key, value in list(best.items()):
                if value is existing:
                    best[key] = candidate
    seen: set[int] = set()
    unique: list[Candidate] = []
    for candidate in best.values():
        if id(candidate) in seen:
            continue
        seen.add(id(candidate))
        unique.append(candidate)
    return unique


async def search(query: str, client: SafeClient, limit: int = 10) -> tuple[list[Candidate], dict[str, str]]:
    """Query all four sources; a failed source is reported, not raised."""
    query = query.strip()
    adapters = {
        "arxiv": arxiv,
        "semanticscholar": semantic_scholar,
        "openalex": openalex,
        "crossref": crossref,
    }
    results = await asyncio.gather(
        *(adapter(query, client, limit) for adapter in adapters.values()),
        return_exceptions=True,
    )
    statuses: dict[str, str] = {}
    found: list[Candidate] = []
    for name, result in zip(adapters, results, strict=True):
        if isinstance(result, BaseException):
            logger.warning("discover source %s failed: %s", name, result)
            statuses[name] = f"error: {result}"
        else:
            statuses[name] = "ok"
            found.extend(result)
    unique = _dedupe(found)
    for candidate in unique:
        candidate.pdf_url = safe_pdf_url(candidate.pdf_url)
    return unique, statuses
