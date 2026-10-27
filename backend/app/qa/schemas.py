"""QA payloads (01 §9, openapi `QAAnswer`).

The shapes here are the contract's: a citation always carries an `Anchor`
(`doc_id`, `block_id`, `page`, `bbox`) and never a chunk id, because the reader
draws a box on the page and a chunk has no single box (H01). The four flag kinds
are the ones `openapi.yaml` names; an answer may carry several.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..models.schemas import Anchor

FlagKind = Literal["invalid_citation", "ungrounded_number", "uncited_claim", "weak_support"]


class Citation(BaseModel):
    marker: str
    anchor: Anchor
    quote: str = ""


class QaFlag(BaseModel):
    kind: FlagKind
    text: str


class QAAnswer(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    refused: bool = False
    flags: list[QaFlag] = Field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")


class CompareCell(BaseModel):
    """One paper's value on one dimension, with the anchors supporting it.

    `text` is copied from the source and checked against it; a cell with no
    evidence says `未在原文找到` and carries no citation (H01/H02).
    """

    text: str
    citations: list[Anchor] = Field(default_factory=list)


class CompareRow(BaseModel):
    dimension: str
    cells: dict[str, CompareCell] = Field(default_factory=dict)


class CompareTable(BaseModel):
    """The openapi `CompareTable`: rows are dimensions, columns are documents."""

    dimensions: list[str] = Field(default_factory=list)
    table: list[CompareRow] = Field(default_factory=list)
    summary: str = ""
    flags: list[QaFlag] = Field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")
