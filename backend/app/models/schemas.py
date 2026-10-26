"""Pydantic models mirroring the document model in 01 §3.

These are the contract the rest of the system reads. Field names must match
the spec exactly.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

BlockType = Literal[
    "heading",
    "paragraph",
    "table",
    "figure",
    "formula",
    "caption",
    "reference",
    "footnote",
    "list_item",
]
SourceKind = Literal["vector", "scanned", "mixed"]
DocStatus = Literal["uploading", "parsing", "ready", "partial", "failed"]


class BBox(BaseModel):
    """PDF point coordinates, origin top-left."""

    x0: float
    y0: float
    x1: float
    y1: float

    @classmethod
    def from_seq(cls, seq: list[float]) -> BBox:
        return cls(x0=seq[0], y0=seq[1], x1=seq[2], y1=seq[3])

    def to_seq(self) -> list[float]:
        return [self.x0, self.y0, self.x1, self.y1]


class Anchor(BaseModel):
    doc_id: str
    block_id: str
    page: int
    bbox: list[float]


class Author(BaseModel):
    name: str
    affiliation: str | None = None
    anchor: Anchor | None = None


class AbstractMeta(BaseModel):
    text: str
    anchor: Anchor | None = None


class DocMeta(BaseModel):
    title: str = ""
    authors: list[Author] = Field(default_factory=list)
    abstract: AbstractMeta | None = None
    year: int | None = None
    venue: str | None = None


class OutlineItem(BaseModel):
    id: str
    level: int
    title: str
    page: int
    block_id: str


class Block(BaseModel):
    id: str
    type: BlockType
    page: int
    bbox: list[float]
    reading_order: int
    section_id: str | None = None
    text: str = ""
    latex: str | None = None
    html: str | None = None
    asset_id: str | None = None
    lang: str = "en"
    confidence: float = 1.0
    bold: bool = False


class Reference(BaseModel):
    id: str
    index: int
    raw: str
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    block_id: str = ""
    bbox: list[float] = Field(default_factory=list)


class Citation(BaseModel):
    id: str
    marker: str
    ref_ids: list[str] = Field(default_factory=list)
    block_id: str
    bbox: list[float] = Field(default_factory=list)
    method: Literal["link_annotation", "regex"] = "regex"


class Asset(BaseModel):
    id: str
    kind: Literal["figure", "table", "formula"]
    page: int
    bbox: list[float]
    path: str


class DocumentModel(BaseModel):
    doc_id: str
    sha256: str
    arxiv_id: str | None = None
    version: str | None = None
    page_count: int
    source_kind: SourceKind
    meta: DocMeta
    outline: list[OutlineItem] = Field(default_factory=list)
    blocks: list[Block] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    assets: list[Asset] = Field(default_factory=list)


class DedupInfo(BaseModel):
    level: Literal["exact_duplicate", "same_paper_other_version", "content_duplicate", "possible_duplicate"]
    matched_doc_id: str
    similarity: float
    existing_version: str | None = None
    new_version: str | None = None
    suggestion: Literal["keep_existing", "replace", "ask"]
    reason: str
