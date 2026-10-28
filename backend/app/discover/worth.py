"""Reference worth score (01 §10, T5.2).

Every signal below is read from rows the parser already stored — citation
markers, the block each marker sits in, that block's heading, the document's
own authors, and any external record with GitHub stars. Nothing is guessed and
nothing is model-generated, so a reader can verify each reason against the
paper (H02/H06). The weights come from `Settings` (``WORTH_*``), and
``min_score`` is the reader's slider.

The core is a pure function, `score_reference`, which makes the score easy to
test and guarantees the same rows always produce the same number. `load_scores`
adds the storage step: it recomputes only when a row's stored value differs,
so `GET /documents/{id}/references` returns current scores without rewriting
them on every read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models.orm import Block as BlockRow
from ..models.orm import CitationRow, Document, PaperExt, ReferenceRow
from .sources import normalize_title

_USAGE = re.compile(
    r"\b(?:we (?:use|used|follow|adopt|employ|extend|build on|compare)|"
    r"based on|following|extends?|extended|compared (?:with|to)|builds? on|inspired by)\b",
    re.IGNORECASE,
)
_METHOD = re.compile(
    r"\b(?:methods?|approach|architecture|experiments?|evaluation|results?|"
    r"implementation|training|setup|ablation)\b",
    re.IGNORECASE,
)
_RELATED = re.compile(r"\brelated work\b|\brelated\b|相关工作", re.IGNORECASE)
_BASELINE = re.compile(r"\bbaseline|comparison|compare|compared", re.IGNORECASE)
_SELF_SPLIT = re.compile(r"[^\w一-鿿]+")


@dataclass(frozen=True)
class WorthWeights:
    per_citation: float = 18.0
    citation_cap: int = 3
    method_section: float = 12.0
    usage_context: float = 10.0
    baseline_table: float = 12.0
    merged_penalty: float = 12.0
    self_penalty: float = 5.0
    external_bonus: float = 8.0
    external_stars: int = 100

    @classmethod
    def from_settings(cls) -> WorthWeights:
        settings = get_settings()
        return cls(
            per_citation=settings.worth_per_citation,
            citation_cap=settings.worth_citation_cap,
            method_section=settings.worth_method_section,
            usage_context=settings.worth_usage_context,
            baseline_table=settings.worth_baseline_table,
            merged_penalty=settings.worth_merged_penalty,
            self_penalty=settings.worth_self_penalty,
            external_bonus=settings.worth_external_bonus,
            external_stars=settings.worth_external_stars,
        )


@dataclass
class Evidence:
    """Everything `score_reference` needs, loaded once for the whole document."""

    citations: dict[str, list[CitationRow]]
    blocks: dict[str, BlockRow]
    sections: dict[str, str]
    external_stars: dict[str, int]
    authors: list[str]


def _short_id(value: str) -> str:
    """A stored citation links to `r3`, while the row is `doc:r3`."""
    return value.rsplit(":", 1)[-1]


def _points(value: float) -> str:
    return f"{value:+.0f}" if float(value).is_integer() else f"{value:+.1f}"


def _surname(name: str) -> str:
    """The comparable part of a name in both "Ada Lovelace" and "Lovelace, Ada"."""
    head = name.split(",", 1)[0] if "," in name else name
    parts = [part for part in _SELF_SPLIT.split(head.strip().lower()) if part]
    return parts[-1] if parts else ""


def _section_title(block: BlockRow | None, sections: dict[str, str]) -> str:
    if block is None or not block.section_id:
        return ""
    return sections.get(block.section_id, "")


def score_reference(
    reference: ReferenceRow,
    evidence: Evidence,
    weights: WorthWeights | None = None,
) -> tuple[float, list[str]]:
    """Return (0–100 score, human-checkable reasons) for one reference."""
    weights = weights or WorthWeights()
    ref_id = _short_id(reference.id)
    citations = evidence.citations.get(ref_id, [])
    reasons: list[str] = []
    score = 0.0

    if citations:
        counted = min(len(citations), weights.citation_cap)
        points = counted * weights.per_citation
        score += points
        if len(citations) > weights.citation_cap:
            reasons.append(
                f"正文被引 {len(citations)} 次（按 {weights.citation_cap} 次封顶，{_points(points)}）"
            )
        else:
            reasons.append(f"正文被引 {len(citations)} 次（{_points(points)}）")
    else:
        reasons.append("正文未找到引用（+0）")

    blocks = [evidence.blocks.get(citation.block_id) for citation in citations]
    titles = [_section_title(block, evidence.sections) for block in blocks]

    if any(_METHOD.search(title) for title in titles):
        score += weights.method_section
        reasons.append(f"引用出现在方法/实验章节（{_points(weights.method_section)}）")

    phrase: str | None = None
    for block in blocks:
        if block is None:
            continue
        match = _USAGE.search(block.text or "")
        if match is not None:
            phrase = match.group(0)
            break
    if phrase is not None:
        score += weights.usage_context
        reasons.append(f"引用上下文含 “{phrase}”（{_points(weights.usage_context)}）")

    on_table = any(
        block is not None
        and (
            block.type == "table"
            or (block.type == "caption" and bool(_BASELINE.search(block.text or "")))
        )
        for block in blocks
    )
    if on_table:
        score += weights.baseline_table
        reasons.append(f"引用出现在基线对比表（{_points(weights.baseline_table)}）")

    external = max(
        (
            stars
            for key in _external_keys(reference)
            if (stars := evidence.external_stars.get(key)) is not None
        ),
        default=0,
    )
    if external >= weights.external_stars:
        score += weights.external_bonus
        reasons.append(f"外部库标记：开源代码 ⭐{external}（{_points(weights.external_bonus)}）")

    merged = any(
        len(citation.ref_ids or []) >= 4 and _RELATED.search(title)
        for citation, title in zip(citations, titles, strict=False)
    )
    if merged:
        score -= weights.merged_penalty
        reasons.append(
            f"仅出现在 Related Work 的 ≥4 篇合并引用（{_points(-weights.merged_penalty)}）"
        )

    own = {_surname(name) for name in evidence.authors if name.strip()}
    ref_authors = {_surname(name) for name in (reference.authors or []) if name.strip()}
    if own & ref_authors:
        score -= weights.self_penalty
        reasons.append(f"自引（{_points(-weights.self_penalty)}，不剔除）")

    return round(min(100.0, max(0.0, score)), 1), reasons


def _external_keys(reference: ReferenceRow) -> list[str]:
    keys: list[str] = []
    if reference.arxiv_id:
        keys.append(f"arxiv:{reference.arxiv_id}")
    if reference.title:
        keys.append(f"title:{normalize_title(reference.title)}")
    return keys


async def _external_marks(session: AsyncSession, weights: WorthWeights) -> dict[str, int]:
    rows = await session.execute(
        select(PaperExt.source, PaperExt.ext_id, PaperExt.title, PaperExt.stars).where(
            PaperExt.stars.is_not(None), PaperExt.stars >= weights.external_stars
        )
    )
    marks: dict[str, int] = {}
    for source, ext_id, title, stars in rows:
        if stars is None:
            continue
        if source == "arxiv" and ext_id:
            marks[f"arxiv:{ext_id}"] = stars
        if title:
            marks[f"title:{normalize_title(title)}"] = stars
    return marks


async def _evidence(session: AsyncSession, doc_id: str, weights: WorthWeights) -> Evidence:
    citations = list(
        await session.scalars(select(CitationRow).where(CitationRow.doc_id == doc_id))
    )
    by_ref: dict[str, list[CitationRow]] = {}
    for citation in citations:
        for ref_id in citation.ref_ids or []:
            by_ref.setdefault(_short_id(ref_id), []).append(citation)

    block_ids = {citation.block_id for citation in citations if citation.block_id}
    blocks: dict[str, BlockRow] = {}
    if block_ids:
        rows = await session.scalars(
            select(BlockRow).where(BlockRow.doc_id == doc_id, BlockRow.id.in_(block_ids))
        )
        blocks = {row.id: row for row in rows}

    section_ids = {row.section_id for row in blocks.values() if row.section_id}
    sections: dict[str, str] = {}
    if section_ids:
        headings = await session.scalars(
            select(BlockRow).where(BlockRow.doc_id == doc_id, BlockRow.id.in_(section_ids))
        )
        sections = {row.id: row.text for row in headings}

    return Evidence(
        citations=by_ref,
        blocks=blocks,
        sections=sections,
        external_stars=await _external_marks(session, weights),
        authors=_document_authors(await session.get(Document, doc_id)),
    )


def _document_authors(doc: Document | None) -> list[str]:
    if doc is None or not isinstance(doc.meta, dict):
        return []
    authors = doc.meta.get("authors")
    if not isinstance(authors, list):
        return []
    return [str(name) for name in authors if isinstance(name, str)]


async def load_scores(session: AsyncSession, doc_id: str) -> list[ReferenceRow]:
    """All references with current scores, persisted when they changed."""
    refs = list(
        await session.scalars(
            select(ReferenceRow)
            .where(ReferenceRow.doc_id == doc_id)
            .order_by(ReferenceRow.index)
        )
    )
    if not refs:
        return []
    weights = WorthWeights.from_settings()
    evidence = await _evidence(session, doc_id, weights)
    changed = False
    for reference in refs:
        score, reasons = score_reference(reference, evidence, weights)
        if reference.worth_score != score or list(reference.worth_reasons or []) != reasons:
            reference.worth_score = score
            reference.worth_reasons = reasons
            changed = True
    if changed:
        await session.commit()
    return refs


def partition(
    refs: list[ReferenceRow], min_score: float, limit: int
) -> tuple[list[ReferenceRow], list[dict[str, Any]]]:
    """Split references into the kept batch (bounded) and exclusion records."""
    kept: list[ReferenceRow] = []
    excluded: list[dict[str, Any]] = []
    for reference in refs:
        score = float(reference.worth_score or 0.0)
        if score < min_score:
            excluded.append(_item(reference, "excluded", f"含金量 {score:g} 低于阈值 {min_score:g}"))
        elif len(kept) >= limit:
            excluded.append(
                _item(
                    reference,
                    "over_limit",
                    f"超过单次导入上限 {limit} 篇；再次运行会继续导入",
                )
            )
        else:
            kept.append(reference)
    return kept, excluded


def _item(reference: ReferenceRow, status: str, reason: str) -> dict[str, Any]:
    return {
        "index": reference.index,
        "title": reference.title or reference.raw[:160],
        "score": float(reference.worth_score or 0.0),
        "status": status,
        "reason": reason,
        "reasons": list(reference.worth_reasons or []),
    }
