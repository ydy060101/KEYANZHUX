"""Resolve and download a candidate's PDF (T5.1).

A candidate found by search is not yet a document: the PDF has to be fetched
from a whitelisted host, checked to be a PDF, deduplicated by content and
handed to the parse pipeline. This module does the first three steps and
returns the bytes plus metadata; the import job owns the database rows.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import InvalidRequest, NotFound
from ..models.orm import PaperExt
from .http import SafeClient, check_url
from .sources import CROSSREF, OPENALEX, S2_PAPER, Candidate, _year

logger = logging.getLogger(__name__)

MAX_PDF_BYTES = 200 * 1024 * 1024


@dataclass
class Resolved:
    pdf_url: str
    title: str | None
    arxiv_id: str | None
    authors: list[str]
    year: int | None
    abstract: str | None
    doi: str | None


def _lookup_url(source: str, ext_id: str) -> str:
    if source == "semanticscholar":
        return f"{S2_PAPER}/{ext_id}"
    if source == "openalex":
        return f"{OPENALEX}/{ext_id}"
    if source == "crossref":
        return f"{CROSSREF}/{ext_id}"
    raise InvalidRequest("未知来源", code="unknown_source", detail={"source": source})


async def _lookup(source: str, ext_id: str, client: SafeClient) -> dict[str, Any]:
    """Ask the source itself for the record, when no cached row has it."""
    if source == "arxiv":
        return {}
    params = (
        {"fields": "title,authors,year,abstract,externalIds,openAccessPdf,url"}
        if source == "semanticscholar"
        else None
    )
    body = await client.get(_lookup_url(source, ext_id), source=source, params=params)
    payload: dict[str, Any] = json.loads(body)
    if source == "semanticscholar":
        open_pdf = payload.get("openAccessPdf") or {}
        external = payload.get("externalIds") or {}
        return {
            "title": payload.get("title"),
            "authors": [a.get("name", "") for a in payload.get("authors") or [] if a.get("name")],
            "year": _year(payload.get("year")),
            "abstract": payload.get("abstract"),
            "pdf_url": open_pdf.get("url"),
            "doi": external.get("DOI"),
            "arxiv_id": external.get("ArXiv"),
        }
    if source == "openalex":
        open_access = payload.get("open_access") or {}
        location = payload.get("primary_location") or {}
        return {
            "title": payload.get("title") or payload.get("display_name"),
            "authors": [
                name
                for authorship in payload.get("authorships") or []
                if (name := (authorship.get("author") or {}).get("display_name"))
            ],
            "year": _year(payload.get("publication_year")),
            "abstract": None,
            "pdf_url": open_access.get("oa_url") or location.get("pdf_url"),
            "doi": (payload.get("doi") or "").replace("https://doi.org/", "") or None,
            "arxiv_id": None,
        }
    # crossref
    message = payload.get("message") or {}
    links = message.get("link") or []
    return {
        "title": (message.get("title") or [None])[0],
        "authors": [
            " ".join(part for part in (a.get("given"), a.get("family")) if part)
            for a in message.get("author") or []
        ],
        "year": _year(((message.get("issued") or {}).get("date-parts") or [[None]])[0][0]),
        "abstract": None,
        "pdf_url": next((link.get("URL") for link in links if link.get("content-type") == "application/pdf"), None),
        "doi": message.get("DOI"),
        "arxiv_id": None,
    }


async def resolve(
    session: AsyncSession, source: str, ext_id: str, client: SafeClient
) -> Resolved:
    """The candidate's PDF URL, from the cache table or from the source API."""
    if source == "arxiv":
        return Resolved(
            pdf_url=f"https://arxiv.org/pdf/{ext_id}",
            title=None,
            arxiv_id=ext_id,
            authors=[],
            year=None,
            abstract=None,
            doi=None,
        )

    row = await session.scalar(
        select(PaperExt).where(PaperExt.source == source, PaperExt.ext_id == ext_id)
    )
    if row is not None and row.pdf_url:
        return Resolved(
            pdf_url=row.pdf_url,
            title=row.title or None,
            arxiv_id=None,
            authors=list(row.authors or []),
            year=row.year,
            abstract=row.abstract,
            doi=None,
        )

    record = await _lookup(source, ext_id, client)
    pdf_url = record.get("pdf_url")
    if not pdf_url:
        raise NotFound(
            "该来源没有可直接下载的 PDF",
            code="pdf_unavailable",
            detail={"source": source, "ext_id": ext_id},
        )
    check_url(str(pdf_url))
    if row is None:
        row = PaperExt(
            source=source,
            ext_id=ext_id,
            title=str(record.get("title") or ""),
            authors=list(record.get("authors") or []),
            year=record.get("year"),
            abstract=record.get("abstract"),
            pdf_url=str(pdf_url),
        )
        session.add(row)
    else:
        row.pdf_url = str(pdf_url)
        row.title = row.title or str(record.get("title") or "")
    await session.flush()
    return Resolved(
        pdf_url=str(pdf_url),
        title=record.get("title"),
        arxiv_id=record.get("arxiv_id"),
        authors=list(record.get("authors") or []),
        year=record.get("year"),
        abstract=record.get("abstract"),
        doi=record.get("doi"),
    )


async def download(resolved: Resolved, source: str, client: SafeClient) -> bytes:
    data = await client.download(resolved.pdf_url, source=source)
    if not data.startswith(b"%PDF-"):
        raise InvalidRequest("下载到的文件不是 PDF", code="not_a_pdf")
    if len(data) > MAX_PDF_BYTES:
        raise InvalidRequest("文件超过 200MB 上限", code="file_too_large")
    return data


def store_candidate(session: AsyncSession, candidate: Candidate) -> PaperExt:
    row = PaperExt(
        source=candidate.source,
        ext_id=candidate.ext_id,
        title=candidate.title,
        authors=candidate.authors,
        year=candidate.year,
        abstract=candidate.abstract,
        pdf_url=candidate.pdf_url,
        github_url=candidate.github_url,
        stars=candidate.stars,
    )
    session.add(row)
    return row
