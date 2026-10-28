"""Reference matching for the citation graph (T6.1).

A bibliography entry is matched to a selected document in the order the
architecture states: DOI → arXiv id → normalised-title fuzzy match. The title
step is *containment*: the fraction of the document title's tokens that appear
in the reference text must reach `TITLE_SIM` (0.92), so a reference has to
contain nearly the whole title to be linked — an author name sharing one word
does not qualify. A year, when both sides know one, must agree; with the
current pipeline year is often missing, so an unknown year on either side does
not veto a match (recorded in QUESTIONS.md).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ARXIV = re.compile(r"(?:arxiv)\s*(?:preprint\s*)?[:#]?\s*(\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
DOI = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
YEAR = re.compile(r"(19|20)\d{2}")
TOKENS = re.compile(r"[a-z0-9]{3,}")

TITLE_SIM = 0.92


@dataclass
class Candidate:
    id: str
    title: str
    arxiv_id: str | None
    doi: str | None
    year: int | None


@dataclass
class Match:
    target_id: str
    method: str
    confidence: float


def tokens(text: str) -> set[str]:
    return set(TOKENS.findall(text.lower()))


def extract_arxiv_id(raw: str) -> str | None:
    match = ARXIV.search(raw)
    return match.group(1) if match else None


def extract_doi(raw: str) -> str | None:
    match = DOI.search(raw)
    if not match:
        return None
    value = match.group(0)
    return value.rstrip(".,;)")


def extract_year(raw: str) -> int | None:
    match = YEAR.search(raw)
    return int(match.group(0)) if match else None


def _doi_key(doi: str) -> str:
    return doi.lower().replace("https://doi.org/", "").replace("doi:", "")


def title_similarity(title: str, text: str) -> float:
    """The share of the title's tokens present in the reference text."""
    a = tokens(title)
    if not a:
        return 0.0
    b = tokens(text)
    return len(a & b) / len(a)


def _years_conflict(raw: str, doc_year: int | None) -> bool:
    ref_year = extract_year(raw)
    return bool(ref_year and doc_year and ref_year != doc_year)


def match_reference(raw: str, candidates: list[Candidate]) -> Match | None:
    """The selected document this reference points at, or None (not in graph)."""
    arxiv_id = extract_arxiv_id(raw)
    if arxiv_id:
        for candidate in candidates:
            if candidate.arxiv_id == arxiv_id:
                return Match(candidate.id, "arxiv_id", 1.0)

    doi = extract_doi(raw)
    if doi:
        wanted = _doi_key(doi)
        for candidate in candidates:
            if candidate.doi and _doi_key(candidate.doi) == wanted:
                return Match(candidate.id, "doi", 1.0)

    best: Match | None = None
    for candidate in candidates:
        similarity = title_similarity(candidate.title, raw)
        if similarity < TITLE_SIM:
            continue
        if _years_conflict(raw, candidate.year):
            continue
        if (
            best is None
            or similarity > best.confidence
            or (similarity == best.confidence and candidate.id < best.target_id)
        ):
            best = Match(candidate.id, "title", round(similarity, 3))
    return best
