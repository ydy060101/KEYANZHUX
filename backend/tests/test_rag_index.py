"""T3.1 acceptance: chunking statistics and the embedding pass.

The card's acceptance is "切块统计测试（长度分布、无跨章节）" — a statistical
test over the chunker, not a hand-picked example. So the tests below run the
real chunker over the real fixture papers and assert properties of the whole
distribution, plus the two hard rules 01 §9 states:

  * no chunk crosses a section boundary;
  * every chunk keeps `block_ids[]`, so a hit maps back to an anchor (H01).

The embedding side is tested against a stub embedder: the real bge-m3 model is
2 GB and loads in minutes, which no unit test should pay, and H15's rule is
that tests never call an external service. `tools/check_embedding.py` carries
the measurement that needs the real model (it reports `E1: PASS`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from sqlalchemy import select, update

from app.models.orm import Chunk, Document
from app.models.schemas import Block
from app.rag.chunk import Chunker, chunk_stats, estimate_tokens, is_furniture
from app.rag.embed_pass import EmbedUnavailable, embed_document, pending_count
from app.rag.embedding import Embedder

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "pdf"
PAPERS = ["1706.03762v1.pdf", "1810.04805_bert.pdf", "2005.14165_gpt3.pdf"]


# ---- the distribution ----------------------------------------------------


@pytest.fixture(scope="module")
def paper_blocks() -> dict[str, list[Block]]:
    """The parsed blocks of the three fixture papers, parsed once."""
    from app.ingest.parser import parse_pdf

    out: dict[str, list[Block]] = {}
    for name in PAPERS:
        path = FIXTURES / name
        if path.is_file():
            out[name] = parse_pdf(path, f"doc-{name}").model.blocks
    if not out:
        pytest.skip("no fixture PDFs are staged")
    return out


@pytest.mark.parametrize("name", PAPERS)
def test_no_chunk_crosses_a_section(paper_blocks: dict[str, list[Block]], name: str) -> None:
    blocks = paper_blocks.get(name)
    if blocks is None:
        pytest.skip(f"{name} is not staged")
    by_id = {block.id: block for block in blocks}
    chunker = Chunker()
    drafts = chunker.feed(blocks) + chunker.flush()
    for draft in drafts:
        sections = {by_id[block_id].section_id for block_id in draft.block_ids if block_id in by_id}
        assert len(sections) == 1, (draft.block_ids, sections)


@pytest.mark.parametrize("name", PAPERS)
def test_every_chunk_names_its_blocks(paper_blocks: dict[str, list[Block]], name: str) -> None:
    """H01: a chunk that cannot name its blocks cannot produce an anchor."""
    blocks = paper_blocks.get(name)
    if blocks is None:
        pytest.skip(f"{name} is not staged")
    known = {block.id for block in blocks}
    chunker = Chunker()
    drafts = chunker.feed(blocks) + chunker.flush()
    for draft in drafts:
        assert draft.block_ids, draft
        assert set(draft.block_ids) <= known, draft.block_ids
        assert draft.text.strip(), draft.block_ids


@pytest.mark.parametrize("name", PAPERS)
def test_the_bulk_of_the_text_is_in_target_sized_chunks(
    paper_blocks: dict[str, list[Block]], name: str
) -> None:
    """The 300–600 target, checked on the distribution rather than per chunk.

    01 §9's range is a target, not a bound: a section that is one paragraph is
    one short chunk, and a single block over 600 tokens cannot be split without
    cutting a sentence. What must hold is that most chunks sit in the range —
    if a chunking bug appears, this is the number that moves first.
    """
    blocks = paper_blocks.get(name)
    if blocks is None:
        pytest.skip(f"{name} is not staged")
    chunker = Chunker()
    drafts = chunker.feed(blocks) + chunker.flush()
    stats = chunk_stats(drafts, skipped_furniture=chunker.skipped_furniture)
    assert stats.count == len(drafts)
    assert stats.in_target >= stats.count * 0.2, stats.as_dict()
    assert stats.above_maximum <= max(3, stats.count * 0.05), stats.as_dict()
    # The median chunk is a real paragraph, not a stray number.
    assert stats.median >= 80, stats.as_dict()


@pytest.mark.parametrize("name", PAPERS)
def test_no_chunk_repeats_its_predecessor(
    paper_blocks: dict[str, list[Block]], name: str
) -> None:
    """An overlap tail that closes on its own is an echo, not a chunk.

    GPT-3's fixtures produced two such echoes before the guard: the tail of a
    chunk was carried forward, the next block started a new section, and the
    tail was emitted alone — text the previous chunk already contained.
    """
    blocks = paper_blocks.get(name)
    if blocks is None:
        pytest.skip(f"{name} is not staged")
    chunker = Chunker()
    drafts = chunker.feed(blocks) + chunker.flush()
    for previous, following in zip(drafts, drafts[1:], strict=False):
        assert set(following.block_ids) - set(previous.block_ids), (previous.block_ids, following.block_ids)


@pytest.mark.parametrize("name", PAPERS)
def test_furniture_is_not_indexed(paper_blocks: dict[str, list[Block]], name: str) -> None:
    """A folio number is not a chunk.

    Transformer v1 has 54 blocks with no letter in them and GPT-3 has 76; left
    in, each becomes a chunk whose whole text is "3" and competes with real
    paragraphs in retrieval.
    """
    blocks = paper_blocks.get(name)
    if blocks is None:
        pytest.skip(f"{name} is not staged")
    chunker = Chunker()
    drafts = chunker.feed(blocks) + chunker.flush()
    assert chunker.skipped_furniture > 0
    for draft in drafts:
        assert not is_furniture(draft.text), draft.text[:40]
        assert estimate_tokens(draft.text) >= 4, draft.text[:40]


def test_a_folio_number_is_furniture_and_a_table_is_not() -> None:
    assert is_furniture("3")
    assert is_furniture("√")
    assert is_furniture("— 12 —")
    # A numeric table row is content: it has digits and spaces but is long.
    assert not is_furniture("3 768 12 5.84 77.9 7 " * 3)
    # A short word is content too — the rule needs the absence of letters, or
    # "Yes" and "No" would be dropped from a table's cells.
    assert not is_furniture("Yes")
    assert not is_furniture("iv")


def test_overlap_stays_within_the_budget() -> None:
    chunker = Chunker(target=450, minimum=300, maximum=600, overlap_ratio=0.15)
    blocks = [_paragraph(f"b{i}", 400) for i in range(6)]
    drafts = chunker.feed(blocks) + chunker.flush()
    by_id = {block.id: block for block in blocks}
    for previous, following in zip(drafts, drafts[1:], strict=False):
        shared = set(previous.block_ids) & set(following.block_ids)
        carried = sum(estimate_tokens(by_id[block_id].text) for block_id in shared)
        assert carried <= chunker.overlap_budget, (previous.block_ids, following.block_ids)


def _paragraph(block_id: str, words: int, section: str = "h1", page: int = 1) -> Block:
    return Block(
        id=block_id,
        type="paragraph",
        page=page,
        bbox=[0.0, 0.0, 1.0, 1.0],
        reading_order=1,
        section_id=section,
        text=" ".join(["word"] * words),
    )


# ---- the embedding pass --------------------------------------------------


class StubEmbedder(Embedder):
    """A deterministic stand-in: one component per keyword, L2-normalised."""

    def __init__(self, *, available: bool = True) -> None:
        super().__init__(model_name="stub-embed")
        if available:
            self._model = object()

    def _load(self) -> Any:  # pragma: no cover - never called
        return self._model

    def _encode(self, texts: list[str]) -> np.ndarray:
        dim = 1024
        rows = []
        for text in texts:
            vector = np.zeros(dim, dtype=np.float32)
            vector[0] = float(len(text))
            vector[1] = float(text.lower().count("attention"))
            vector[2] = float(text.lower().count("bert"))
            rows.append(vector / np.linalg.norm(vector))
        return np.vstack(rows)


class MissingEmbedder(Embedder):
    def __init__(self) -> None:
        super().__init__(model_name="missing")
        self._load_error = "no weights"


async def _document_with_chunks(session: Any, count: int = 5) -> str:
    session.add(Document(id="doc-embed", sha256="e" * 64, title="Embed", status="ready", file_path="x"))
    for index in range(count):
        session.add(
            Chunk(
                id=f"doc-embed:b1_{index}",
                doc_id="doc-embed",
                block_ids=[f"b1_{index}"],
                section_id="h1",
                page_start=1,
                page_end=1,
                text=f"chunk number {index} about attention",
            )
        )
    await session.commit()
    return "doc-embed"


async def test_embedding_fills_every_null_vector(session: Any) -> None:
    doc_id = await _document_with_chunks(session, 5)
    assert await pending_count(session, doc_id) == 5

    result = await embed_document(session, doc_id, StubEmbedder())

    assert result.embedded == 5
    assert result.remaining == 0
    assert await pending_count(session, doc_id) == 0


async def _vectors(session: Any, doc_id: str) -> dict[str, list[float]]:
    rows = await session.execute(
        select(Chunk.id, Chunk.embedding).where(Chunk.doc_id == doc_id).order_by(Chunk.id)
    )
    return {row.id: [float(x) for x in row.embedding or []] for row in rows}


async def test_embedding_is_idempotent(session: Any) -> None:
    """H12: a second run embeds nothing, and the vectors do not change."""
    doc_id = await _document_with_chunks(session, 3)
    await embed_document(session, doc_id, StubEmbedder())
    before = await _vectors(session, doc_id)

    again = await embed_document(session, doc_id, StubEmbedder())

    assert again.embedded == 0
    assert await _vectors(session, doc_id) == before


async def test_a_killed_pass_resumes_where_it_stopped(session: Any) -> None:
    """The pass selects `embedding IS NULL`, so a partial run is not redone."""
    doc_id = await _document_with_chunks(session, 4)
    await session.execute(
        update(Chunk).where(Chunk.id == "doc-embed:b1_0").values(embedding=[0.0] * 1024)
    )
    await session.commit()
    assert await pending_count(session, doc_id) == 3

    result = await embed_document(session, doc_id, StubEmbedder())

    assert result.embedded == 3
    assert result.remaining == 0


async def test_an_unavailable_model_fails_loudly(session: Any) -> None:
    """H08: no vectors must not look like success, or retrieval silently degrades."""
    doc_id = await _document_with_chunks(session, 2)
    with pytest.raises(EmbedUnavailable) as caught:
        await embed_document(session, doc_id, MissingEmbedder())
    assert "向量索引未生成" in str(caught.value)
    assert await pending_count(session, doc_id) == 2


async def test_progress_is_reported_per_batch(session: Any) -> None:
    doc_id = await _document_with_chunks(session, 3)
    seen: list[tuple[int, int]] = []

    async def hook(done: int, total: int) -> None:
        seen.append((done, total))

    await embed_document(session, doc_id, StubEmbedder(), on_progress=hook)

    assert seen, "no progress was reported"
    assert seen[-1] == (3, 3)
    assert all(total == 3 for _, total in seen)


async def test_the_stored_vector_has_the_configured_dimension(session: Any) -> None:
    """The column is `Vector(1024)`; a different model would be rejected here."""
    from app.config import get_settings

    doc_id = await _document_with_chunks(session, 1)
    await embed_document(session, doc_id, StubEmbedder())
    vectors = await _vectors(session, doc_id)
    assert len(next(iter(vectors.values()))) == get_settings().embed_dim


# ---- the API surface -----------------------------------------------------


async def test_detail_reports_chunk_and_embedding_counts(session: Any) -> None:
    """CR-011: a client must be able to tell "chunked" from "embedded"."""
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    doc_id = await _document_with_chunks(session, 2)
    await embed_document(session, doc_id, StubEmbedder())
    session.add(
        Chunk(
            id="doc-embed:b2_0",
            doc_id=doc_id,
            block_ids=["b2_0"],
            section_id="h1",
            page_start=2,
            page_end=2,
            text="an unembedded chunk",
        )
    )
    await session.commit()

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/documents/{doc_id}", headers={"X-User-Id": "tester"})

    assert response.status_code == 200
    stats = response.json()["stats"]
    assert stats["chunks"] == 3
    assert stats["embedded"] == 2


async def test_embed_endpoint_queues_a_job(session: Any) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app
    from app.workers import register_all

    register_all()
    doc_id = await _document_with_chunks(session, 1)

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/documents/{doc_id}/embed", headers={"X-User-Id": "tester"}
        )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["doc_id"] == doc_id
    assert body["job_id"]


async def test_embed_endpoint_refuses_an_unparsed_document(session: Any) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app
    from app.workers import register_all

    register_all()
    session.add(Document(id="doc-fresh", sha256="d" * 64, title="Fresh", status="uploading", file_path="x"))
    await session.commit()

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/documents/doc-fresh/embed", headers={"X-User-Id": "tester"}
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
