"""SQLAlchemy tables for the contract in 01 §4."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    # PostgreSQL's ARRAY, not the generic one: only the dialect type supports
    # containment (`tags @> ARRAY['nlp']`).
    type_annotation_map = {dict[str, Any]: JSONB, list[str]: ARRAY(String)}


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    arxiv_id: Mapped[str | None] = mapped_column(String(32), index=True)
    version: Mapped[str | None] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="uploading", index=True)
    source_kind: Mapped[str] = mapped_column(String(16), default="vector")
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    file_path: Mapped[str] = mapped_column(Text)
    # The extracted bibliographic metadata (authors with affiliations, abstract,
    # year, venue) exactly as the parse produced it, anchors included (CR-006).
    # `title` above stays a column because the library list sorts and searches
    # on it; everything else is read only by the reader's structure panel, so a
    # JSON document is a better fit than eight more columns.
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_by: Mapped[str] = mapped_column(String(64), default="default")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parse_error: Mapped[str | None] = mapped_column(Text)

    blocks: Mapped[list[Block]] = relationship(back_populates="document", cascade="all, delete-orphan")
    chunks: Mapped[list[Chunk]] = relationship(back_populates="document", cascade="all, delete-orphan")


class DocFingerprint(Base):
    __tablename__ = "doc_fingerprints"

    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    # 61-bit MinHash values do not fit in a 32-bit integer.
    minhash: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), default=list)
    title_abs_embedding: Mapped[Any | None] = mapped_column(Vector(1024))
    first_pages_text_hash: Mapped[str] = mapped_column(String(64), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Block(Base):
    __tablename__ = "blocks"

    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(16), index=True)
    page: Mapped[int] = mapped_column(Integer, index=True)
    bbox: Mapped[list[float]] = mapped_column(ARRAY(Float))
    reading_order: Mapped[int] = mapped_column(Integer)
    section_id: Mapped[str | None] = mapped_column(String(64), index=True)
    text: Mapped[str] = mapped_column(Text, default="")
    latex: Mapped[str | None] = mapped_column(Text)
    html: Mapped[str | None] = mapped_column(Text)
    asset_id: Mapped[str | None] = mapped_column(String(64))
    lang: Mapped[str] = mapped_column(String(8), default="en")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)

    document: Mapped[Document] = relationship(back_populates="blocks")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    block_ids: Mapped[list[str]] = mapped_column(ARRAY(String))
    section_id: Mapped[str | None] = mapped_column(String(64))
    page_start: Mapped[int] = mapped_column(Integer)
    page_end: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[Any | None] = mapped_column(Vector(1024))
    # A generated tsvector rather than a plain text column: the full-text
    # index must be derived from `text` by PostgreSQL itself, or it can drift
    # from the text it is supposed to index. `english` is named explicitly
    # because the two-argument form is immutable, which a generated column
    # requires, and because a search configuration that changes with a server
    # setting would make the index silently unreproducible (H06).
    tsv: Mapped[Any | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', text)", persisted=True)
    )

    document: Mapped[Document] = relationship(back_populates="chunks")

    # The two indexes retrieval reads (T3.1, 01 §9): a cosine HNSW graph over
    # the vectors and a GIN index over the generated tsvector. Declared here so
    # `create_all` builds them with the table; a database that already has the
    # table gets them from `tools/sync_schema.py` (see ADDED_INDEXES there).
    #
    # `vector_cosine_ops` matches how the retriever compares: bge-m3 vectors
    # are L2-normalised at encode time, so cosine and inner product rank
    # identically, but cosine is the operator the query will use and the index
    # has to match it or PostgreSQL falls back to a sequential scan.
    __table_args__ = (
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
    )


class SectionSummaryRow(Base):
    """The coarse level of the two-level index (T2.5, CR-005).

    A chunk names its section, but a section has no row of its own to hold a
    title and a summary — which is exactly what a reader scans in a 541-page
    book and what a question about "the regularization chapter" needs.
    """

    __tablename__ = "section_summaries"

    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    section_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(Text, default="")
    # Depth in the heading tree, from the tracker that placed it (T2.6): a
    # book with no numbered headings cannot have its level recovered from the
    # title text, and the outline needs it to indent the tree.
    level: Mapped[int] = mapped_column(Integer, default=1)
    page: Mapped[int] = mapped_column(Integer, default=1)
    summary: Mapped[str] = mapped_column(Text, default="")
    block_ids: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)


class ReferenceRow(Base):
    __tablename__ = "references"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    index: Mapped[int] = mapped_column(Integer)
    raw: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str | None] = mapped_column(Text)
    authors: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    year: Mapped[int | None] = mapped_column(Integer)
    doi: Mapped[str | None] = mapped_column(String(128))
    arxiv_id: Mapped[str | None] = mapped_column(String(32))
    block_id: Mapped[str] = mapped_column(String(64), default="")
    bbox: Mapped[list[float]] = mapped_column(ARRAY(Float), default=list)
    worth_score: Mapped[float | None] = mapped_column(Float)
    worth_reasons: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)


class CitationRow(Base):
    __tablename__ = "citations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    marker: Mapped[str] = mapped_column(String(64))
    ref_ids: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    block_id: Mapped[str] = mapped_column(String(64))
    bbox: Mapped[list[float]] = mapped_column(ARRAY(Float), default=list)
    method: Mapped[str] = mapped_column(String(24), default="regex")


class AssetRow(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    page: Mapped[int] = mapped_column(Integer)
    bbox: Mapped[list[float]] = mapped_column(ARRAY(Float))
    path: Mapped[str] = mapped_column(Text)
    # A table's structure as HTML, when the source exposed one (CR-006).
    html: Mapped[str | None] = mapped_column(Text)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    stage: Mapped[str] = mapped_column(String(32), default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    created_by: Mapped[str] = mapped_column(String(64), default="default")


class PaperExt(Base):
    __tablename__ = "papers_ext"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source: Mapped[str] = mapped_column(String(32), index=True)
    ext_id: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    authors: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    year: Mapped[int | None] = mapped_column(Integer)
    abstract: Mapped[str | None] = mapped_column(Text)
    pdf_url: Mapped[str | None] = mapped_column(Text)
    github_url: Mapped[str | None] = mapped_column(Text)
    stars: Mapped[int | None] = mapped_column(Integer)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("source", "ext_id", name="uq_papers_ext_source_ext_id"),)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    paper_id: Mapped[str] = mapped_column(String(64), index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    reasons: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    paper_id: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("user_id", "paper_id", name="uq_feedback_user_paper"),)


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    interest_vector: Mapped[Any | None] = mapped_column(Vector(1024))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TrackingConfig(Base):
    __tablename__ = "tracking_config"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    categories: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    keywords: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    cron: Mapped[str] = mapped_column(String(64), default="0 6 * * *")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Graph(Base):
    __tablename__ = "graphs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    doc_ids: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    nodes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    edges: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    survey: Mapped[str | None] = mapped_column(Text)
    future_work: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Translation(Base):
    __tablename__ = "translations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    block_id: Mapped[str] = mapped_column(String(64))
    lang: Mapped[str] = mapped_column(String(8))
    text: Mapped[str] = mapped_column(Text)
    cache_key: Mapped[str] = mapped_column(String(64), index=True)

    __table_args__ = (UniqueConstraint("doc_id", "block_id", "lang", name="uq_translation_block_lang"),)


class Draft(Base):
    __tablename__ = "drafts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    idea: Mapped[str] = mapped_column(Text)
    outline: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    references: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    bibtex: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    filename: Mapped[str] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text)
    columns: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Figure(Base):
    __tablename__ = "figures"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    dataset_id: Mapped[str | None] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    script: Mapped[str] = mapped_column(Text, default="")
    render_path: Mapped[str | None] = mapped_column(Text)
    caption: Mapped[str | None] = mapped_column(Text)
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QASession(Base):
    __tablename__ = "qa_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(64), index=True, default="default")
    title: Mapped[str] = mapped_column(Text, default="")
    scope: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QAMessage(Base):
    __tablename__ = "qa_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("qa_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    refused: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
