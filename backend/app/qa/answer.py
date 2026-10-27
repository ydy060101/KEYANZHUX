"""The QA pipeline: retrieve → refuse → extract → generate → verify → anchor.

Order matters and follows 01 §9:

  1. **Retrieve** the top 8 chunks (T3.2), scoped to the requested documents.
  2. **Refuse (H03)** when the reranker's best score is below `QA_MIN_SCORE`.
     The gate only applies when the reranker actually ran: the RRF score is on
     a different scale (≈0.03 at best), so comparing it to the same threshold
     would refuse everything whenever the cross-encoder is unavailable.
  3. **Extract (01 §9, metadata questions)** named fields first, keeping only
     values found literally in the block they cite.
  4. **Generate** from numbered evidence only, every sentence citing numbers.
  5. **Verify (H04, H01)** each sentence against the chunks it cites; drop what
     does not check out, map each surviving marker to a `blocks` row, and use
     that row's page and bbox as the anchor.
  6. **Emit** `token` per verified sentence, `anchor` when a marker first
     appears, then `done` with the complete `QAAnswer`.

Generation is a non-streaming call on the `strong` tier. H04 must see a whole
sentence before any of it is shown, and the gateway's H06 cache only applies to
non-streaming calls, so buffering is both the safe and the deterministic
choice. The SSE stream is still incremental at sentence granularity.

When nothing survives verification, the result is a refusal rather than a
partly-unsupported answer: H01 forbids outputting a conclusion with no anchor.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..errors import InvalidRequest
from ..llm.gateway import get_gateway
from ..models.orm import Block, Document
from ..models.schemas import Anchor
from ..rag.embedding import Embedder, get_embedder
from ..rag.retrieve import RetrievalResult, Scope, retrieve
from .extract import extract_fields, is_metadata_question
from .prompt import Evidence, answer_messages, build_evidence
from .schemas import Citation, QAAnswer, QaFlag
from .verify import VerifiedSentence, contains, verifiable_tokens, verify_answer

logger = logging.getLogger(__name__)

REFUSAL_TEXT = "未在所选文献中找到依据。可尝试扩大检索范围或换个问法。"


@dataclass
class QaOutcome:
    """Everything the endpoint streams, and why."""

    answer: QAAnswer
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    stages: dict[str, Any] = field(default_factory=dict)
    evidence: list[Evidence] = field(default_factory=list)


async def run_qa(
    session: AsyncSession,
    question: str,
    scope: Scope,
    *,
    embedder: Embedder | None = None,
    gateway: Any = None,
    limit: int | None = None,
) -> QaOutcome:
    question = question.strip()
    if not question:
        raise InvalidRequest("问题不能为空")
    embedder = embedder or get_embedder()
    gateway = gateway or get_gateway()

    result = await retrieve(session, question, scope, embedder, limit=limit)
    stages: dict[str, Any] = dict(result.stages)
    stages["top_score"] = round(result.top_score, 4)

    reason = _weak_evidence(result)
    if reason is not None:
        return _refusal(reason, stages)

    evidence = await _load_evidence(session, result)
    if not evidence:
        return _refusal("命中的片段没有可用的文本或块锚点", stages)

    facts = await _facts(gateway, question, evidence, stages)
    reply = await gateway.chat(answer_messages(question, evidence, facts), tier="strong")
    raw: str = getattr(reply, "text", "") or ""
    verification = verify_answer(raw, evidence)
    if verification.not_found or not verification.sentences:
        reason = "模型判断所给证据未包含答案" if verification.not_found else "回答未通过证据回验，已拒答"
        return _refusal(reason, stages, verification.flags)

    blocks = await _load_blocks(session, evidence)
    kept, citations, flags = _resolve(verification.sentences, evidence, blocks, verification.flags)
    if not kept:
        return _refusal("引用的片段找不到对应的块锚点", stages, flags)
    if not stages.get("reranked"):
        flags.append(QaFlag(kind="weak_support", text="重排模型不可用，本次按融合排序作答"))
    return _compose(kept, citations, flags, stages, evidence)


# ---- H03 -----------------------------------------------------------------


def _weak_evidence(result: RetrievalResult) -> str | None:
    """The refusal reason, or None when the evidence is strong enough."""
    if not result.hits:
        return "检索未返回任何片段"
    threshold = get_settings().qa_min_score
    if result.stages.get("reranked") and result.top_score < threshold:
        return f"最高重排分 {result.top_score:.3f} 低于阈值 {threshold:.2f}"
    return None


# ---- evidence and extraction --------------------------------------------


async def _load_evidence(session: AsyncSession, result: RetrievalResult) -> list[Evidence]:
    doc_ids = sorted({hit.doc_id for hit in result.hits})
    rows = await session.execute(select(Document.id, Document.title).where(Document.id.in_(doc_ids)))
    titles = {row[0]: row[1] for row in rows}
    return [
        item
        for item in build_evidence(result.hits, titles)
        if item.text.strip() and item.block_ids
    ]


async def _facts(
    gateway: Any, question: str, evidence: list[Evidence], stages: dict[str, Any]
) -> list[tuple[str, str, int]]:
    """Ground-checked fields for a metadata question; empty otherwise."""
    if not is_metadata_question(question):
        return []
    fields = await extract_fields(gateway, question, evidence)
    stages["fields_extracted"] = len(fields)
    facts = [(item.name, item.value, item.evidence) for item in fields if item.value and item.evidence]
    stages["fields_grounded"] = len(facts)
    return facts


# ---- anchors -------------------------------------------------------------


async def _load_blocks(session: AsyncSession, evidence: list[Evidence]) -> dict[tuple[str, str], Block]:
    pairs = {(item.doc_id, block_id) for item in evidence for block_id in item.block_ids}
    if not pairs:
        return {}
    rows = await session.scalars(select(Block).where(tuple_(Block.doc_id, Block.id).in_(list(pairs))))
    return {(row.doc_id, row.id): row for row in rows}


def _anchor(sentence: str, evidence: Evidence, blocks: dict[tuple[str, str], Block]) -> Anchor | None:
    """The block of the cited chunk that best supports the sentence.

    A chunk spans blocks and often pages; the anchor must point at the one
    holding the answer, not merely at the chunk's first block. A matched token
    is weighted by how rare it is in the chunk: "36M" occurs once and locates
    its own page, while "WMT" or "Transformer" occurs in several blocks and
    barely discriminates. Ties keep reading order, and no candidate means the
    citation is dropped rather than given an invented bbox (H01, H06).
    """
    candidates = [
        blocks[(evidence.doc_id, block_id)]
        for block_id in evidence.block_ids
        if (evidence.doc_id, block_id) in blocks
    ]
    if not candidates:
        return None
    tokens = verifiable_tokens(sentence)
    counts = {token: max(1, evidence.text.count(token)) for token in tokens}
    best: Block | None = None
    best_score = -1.0
    for block in sorted(candidates, key=lambda row: (row.reading_order, row.id)):
        score = sum(1.0 / counts[token] for token in tokens if contains(block.text or "", token))
        if score > best_score:
            best, best_score = block, score
    assert best is not None
    return Anchor(doc_id=evidence.doc_id, block_id=best.id, page=best.page, bbox=list(best.bbox or []))


def _resolve(
    sentences: list[VerifiedSentence],
    evidence: list[Evidence],
    blocks: dict[tuple[str, str], Block],
    flags: list[QaFlag],
) -> tuple[list[tuple[VerifiedSentence, list[str]]], list[Citation], list[QaFlag]]:
    """Map marker numbers to citations; drop sentences left without one."""
    kept: list[tuple[VerifiedSentence, list[str]]] = []
    citations: dict[str, Citation] = {}
    flags = list(flags)
    for sentence in sentences:
        markers: list[str] = []
        for number in sentence.markers:
            anchor = _anchor(sentence.text, evidence[number - 1], blocks)
            if anchor is None:
                flags.append(
                    QaFlag(kind="invalid_citation", text=f"证据 [{number}] 找不到对应块，已忽略")
                )
                continue
            marker = f"[{number}]"
            if marker not in citations:
                citations[marker] = Citation(
                    marker=marker, anchor=anchor, quote=sentence.quotes.get(number, "")
                )
            markers.append(marker)
        if markers:
            kept.append((sentence, markers))
    return kept, list(citations.values()), flags


# ---- assembly ------------------------------------------------------------


def _compose(
    kept: list[tuple[VerifiedSentence, list[str]]],
    citations: list[Citation],
    flags: list[QaFlag],
    stages: dict[str, Any],
    evidence: list[Evidence],
) -> QaOutcome:
    answer = QAAnswer(
        answer=" ".join(sentence.text for sentence, _ in kept),
        citations=citations,
        refused=False,
        flags=flags,
    )
    by_marker = {citation.marker: citation for citation in citations}
    events: list[tuple[str, dict[str, Any]]] = []
    emitted: set[str] = set()
    for index, (sentence, markers) in enumerate(kept):
        text = sentence.text + (" " if index < len(kept) - 1 else "")
        events.append(("token", {"text": text}))
        for marker in markers:
            if marker in emitted:
                continue
            emitted.add(marker)
            citation = by_marker[marker]
            events.append(
                (
                    "anchor",
                    {
                        "marker": marker,
                        "anchor": citation.anchor.model_dump(mode="json"),
                        "quote": citation.quote,
                    },
                )
            )
    events.append(("done", answer.as_dict()))
    return QaOutcome(answer=answer, events=events, stages=stages, evidence=evidence)


def _refusal(reason: str, stages: dict[str, Any], extra: list[QaFlag] | None = None) -> QaOutcome:
    stages["refusal"] = reason
    flags = [QaFlag(kind="weak_support", text=reason)]
    for flag in extra or []:
        if flag.kind == "weak_support" and flag.text == reason:
            continue
        flags.append(flag)
    answer = QAAnswer(answer=REFUSAL_TEXT, citations=[], refused=True, flags=flags)
    events: list[tuple[str, dict[str, Any]]] = [
        ("token", {"text": REFUSAL_TEXT}),
        ("done", answer.as_dict()),
    ]
    return QaOutcome(answer=answer, events=events, stages=stages)
