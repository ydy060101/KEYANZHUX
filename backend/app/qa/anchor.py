"""Turning a cited chunk into a page-and-bbox anchor (H01).

A chunk is a range of blocks, and the anchor has to be one block: the reader
highlights a rectangle on a page, and a chunk has no single rectangle. Both the
QA path and the compare path need this, which is why it lives here rather than
inside `answer`.
"""

from __future__ import annotations

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.orm import Block
from ..models.schemas import Anchor
from .prompt import Evidence
from .verify import grounds, verifiable_tokens


async def load_blocks(session: AsyncSession, evidence: list[Evidence]) -> dict[tuple[str, str], Block]:
    """Fetch the `blocks` rows named by a set of evidence items in one query."""
    pairs = {(item.doc_id, block_id) for item in evidence for block_id in item.block_ids}
    if not pairs:
        return {}
    rows = await session.scalars(select(Block).where(tuple_(Block.doc_id, Block.id).in_(list(pairs))))
    return {(row.doc_id, row.id): row for row in rows}


def pick_anchor(sentence: str, evidence: Evidence, blocks: dict[tuple[str, str], Block]) -> Anchor | None:
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
        score = sum(1.0 / counts[token] for token in tokens if grounds(block.text or "", token))
        if score > best_score:
            best, best_score = block, score
    assert best is not None
    return Anchor(doc_id=evidence.doc_id, block_id=best.id, page=best.page, bbox=list(best.bbox or []))
