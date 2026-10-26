"""Metadata extraction: page-1 rules plus an anchored LLM pass (01 §7 stage 5).

The LLM sees the first-page blocks with their ids and must return the id each
field came from, so every extracted value carries a verifiable anchor (H01).
If the model is unavailable the rule-based result is kept instead of failing.
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel, Field

from ..llm.errors import LLMError
from ..llm.gateway import LLMGateway
from ..llm.safety import wrap_data
from ..models.schemas import AbstractMeta, Anchor, Author, Block, DocMeta
from . import pdfio

logger = logging.getLogger(__name__)

MAX_BLOCKS = 24


class _Field(BaseModel):
    """One extracted value plus the block ids it was read from (H01)."""

    value: str | int | None = None
    source_ids: list[str] = Field(default_factory=list)


class _LLMAuthor(BaseModel):
    name: str
    affiliation: str | None = None
    source_ids: list[str] = Field(default_factory=list)


class _LLMMeta(BaseModel):
    title: _Field = Field(default_factory=_Field)
    authors: list[_LLMAuthor] = Field(default_factory=list)
    abstract: _Field = Field(default_factory=_Field)
    year: _Field = Field(default_factory=_Field)
    venue: _Field = Field(default_factory=_Field)


SYSTEM = (
    "You extract bibliographic metadata from the first page of a research paper. "
    "Use only the supplied blocks. Never invent a title, author, affiliation or year. "
    "For every field return the id of the block the text came from."
)


def _page_one_blocks(blocks: list[Block]) -> list[Block]:
    return [block for block in blocks if block.page == 1][:MAX_BLOCKS]


def _render(blocks: list[Block]) -> str:
    lines = []
    for block in blocks:
        text = " ".join(block.text.split())
        lines.append(f"[{block.id}] {text[:400]}")
    return wrap_data("\n".join(lines))


def _anchor(block: Block, doc_id: str) -> Anchor:
    return Anchor(doc_id=doc_id, block_id=block.id, page=block.page, bbox=block.bbox)


def rule_based_meta(doc: pdfio.Document, blocks: list[Block], doc_id: str) -> DocMeta:
    """Fallback used when the LLM is unavailable."""
    first_page = _page_one_blocks(blocks)
    title = ""
    for block in first_page[:5]:
        text = " ".join(block.text.split())
        if len(text) > 12 and not text.lower().startswith(("arxiv", "abstract")):
            title = text[:300]
            break
    if not title:
        title = pdfio.document_metadata(doc).get("title") or ""

    authors: list[Author] = []
    for block in first_page[1:8]:
        line = " ".join(block.text.split())
        if not line or "@" in line or len(line) > 120:
            continue
        if line.lower().startswith(("abstract", "arxiv", "keywords")):
            break
        words = line.split()
        if not 1 <= len(words) <= 12:
            continue
        if line.endswith(".") and sum(1 for w in words if w[:1].islower()) > 3:
            continue
        authors.append(Author(name=line.replace("*", "").replace("†", "").strip(), anchor=_anchor(block, doc_id)))
    return DocMeta(title=title, authors=authors)


async def extract_meta_llm(
    doc: pdfio.Document,
    blocks: list[Block],
    doc_id: str,
    gateway: LLMGateway,
    *,
    tier: str = "fast",
) -> DocMeta:
    """LLM extraction with anchor enforcement; falls back to rules on failure."""
    page_blocks = _page_one_blocks(blocks)
    if not page_blocks:
        return rule_based_meta(doc, blocks, doc_id)

    by_id = {block.id: block for block in page_blocks}
    prompt = (
        "Extract the paper's title, the full author list with affiliations, the abstract "
        "text, the publication year and the venue. Copy the abstract verbatim. "
        "Return exactly this JSON shape and nothing else:\n"
        "{\n"
        '  "title": {"value": "...", "source_ids": ["b1"]},\n'
        '  "authors": [{"name": "...", "affiliation": "...", "source_ids": ["b2"]}],\n'
        '  "abstract": {"value": "...", "source_ids": ["b4"]},\n'
        '  "year": {"value": 2017, "source_ids": ["b1"]},\n'
        '  "venue": {"value": null, "source_ids": []}\n'
        "}\n"
        "Every source_ids entry must be a block id that appears below. "
        "If a field is not visible, use null and an empty list.\n\n"
        f"{_render(page_blocks)}"
    )
    try:
        meta = await gateway.chat_json(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
            _LLMMeta,
            tier=tier,  # type: ignore[arg-type]
            cache_prefix=SYSTEM,
        )
    except LLMError as exc:
        logger.warning("metadata LLM failed, using rules: %s", exc)
        return rule_based_meta(doc, blocks, doc_id)

    fallback = rule_based_meta(doc, blocks, doc_id)
    title = str(meta.title.value or "").strip() or fallback.title

    authors: list[Author] = []
    for author in meta.authors:
        name = author.name.strip()
        if not name:
            continue
        anchor = next((_anchor(by_id[bid], doc_id) for bid in author.source_ids if bid in by_id), None)
        authors.append(Author(name=name, affiliation=(author.affiliation or None), anchor=anchor))
    if not authors:
        authors = fallback.authors

    abstract_meta: AbstractMeta | None = None
    abstract_value = str(meta.abstract.value or "").strip()
    if abstract_value:
        anchor = next((_anchor(by_id[bid], doc_id) for bid in meta.abstract.source_ids if bid in by_id), None)
        abstract_meta = AbstractMeta(text=abstract_value, anchor=anchor)

    year: int | None = None
    raw_year = meta.year.value
    if isinstance(raw_year, int):
        year = raw_year
    elif isinstance(raw_year, str) and raw_year.isdigit():
        year = int(raw_year)
    if year is None:
        for block in page_blocks:
            match = re.search(r"(19|20)\d{2}", block.text)
            if match:
                year = int(match.group(0))
                break

    venue = str(meta.venue.value).strip() if meta.venue.value else None
    return DocMeta(
        title=title,
        authors=authors,
        abstract=abstract_meta,
        year=year,
        venue=venue,
    )
