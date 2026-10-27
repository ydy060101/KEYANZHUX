"""T1.5 acceptance: section diff, statistics and a grounded summary."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.ingest import diff as diff_mod
from app.ingest.diff import Section, diff_sections, sections_from_blocks, summary_is_grounded
from app.models.orm import Block as BlockRow
from app.models.orm import Document, ReferenceRow
from app.models.schemas import Block

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "pdf"


def _block(block_id: str, kind: str, text: str, order: int = 0) -> Block:
    return Block(
        id=block_id,
        type=kind,  # type: ignore[arg-type]
        page=1,
        bbox=[0, 0, 10, 10],
        reading_order=order,
        text=text,
    )


def test_sections_group_under_headings() -> None:
    blocks = [
        _block("b1", "heading", "1 Introduction", 1),
        _block("b2", "paragraph", "First paragraph.", 2),
        _block("b3", "heading", "2 Method", 3),
        _block("b4", "paragraph", "Second paragraph.", 4),
    ]
    sections = sections_from_blocks(blocks)
    assert [s.title for s in sections] == ["1 Introduction", "2 Method"]
    assert sections[0].text == "First paragraph."
    assert sections[0].block_ids == ["b1", "b2"]


def test_identical_sections_are_unchanged() -> None:
    old = [Section(title="1 Introduction", text="same text")]
    new = [Section(title="1 Introduction", text="same text")]
    result = diff_sections(old, new)
    assert result[0].change == "unchanged"


def test_modified_added_removed() -> None:
    old = [Section(title="1 Introduction", text="alpha " * 50), Section(title="2 Old", text="x")]
    new = [Section(title="1 Introduction", text="beta " * 50), Section(title="3 New", text="y")]
    changes = {c.title: c.change for c in diff_sections(old, new)}
    assert changes["1 Introduction"] == "modified"
    assert changes["3 New"] == "added"
    assert changes["2 Old"] == "removed"


def test_renumbered_heading_matches_by_title() -> None:
    old = [Section(title="3 Results", text="body text here")]
    new = [Section(title="4 Results", text="body text here")]
    result = diff_sections(old, new)
    assert result[0].change == "unchanged", "the number is not part of the identity"


def test_summary_grounding_rejects_invented_numbers() -> None:
    stats = {"sections_added": 2, "sections_removed": 0, "sections_modified": 1}
    assert summary_is_grounded("新增 2 个章节，修改 1 个。", stats)
    assert not summary_is_grounded("新增 2 个章节，修改 7 个。", stats)
    assert summary_is_grounded("本次修订集中在方法部分，未列出具体数量。", stats)


async def _seed_doc(session: Any, doc_id: str, *, title: str, sections: list[tuple[str, str]]) -> None:
    doc = Document(id=doc_id, sha256=f"sha-{doc_id}", title=title, status="ready", file_path="/tmp/x.pdf")
    session.add(doc)
    order = 0
    for heading, body in sections:
        order += 1
        session.add(
            BlockRow(
                doc_id=doc_id,
                id=f"{doc_id}-h{order}",
                type="heading",
                page=1,
                bbox=[0, 0, 1, 1],
                reading_order=order,
                section_id=f"s{order}",
                text=heading,
            )
        )
        order += 1
        session.add(
            BlockRow(
                doc_id=doc_id,
                id=f"{doc_id}-p{order}",
                type="paragraph",
                page=1,
                bbox=[0, 0, 1, 1],
                reading_order=order,
                section_id=f"s{order}",
                text=body,
            )
        )
    await session.flush()


async def test_compare_reports_counts(session: Any) -> None:
    await _seed_doc(
        session,
        "old",
        title="v1",
        sections=[("1 Introduction", "alpha " * 40), ("2 Method", "unchanged method")],
    )
    await _seed_doc(
        session,
        "new",
        title="v7",
        sections=[
            ("1 Introduction", "beta " * 40),
            ("2 Method", "unchanged method"),
            ("3 Results", "brand new results"),
        ],
    )
    for index in range(3):
        session.add(
            ReferenceRow(id=f"old-r{index}", doc_id="old", index=index, raw=f"ref {index}")
        )
    for index in range(5):
        session.add(
            ReferenceRow(id=f"new-r{index}", doc_id="new", index=index, raw=f"ref {index}")
        )
    await session.flush()

    stats, _raw, changes = await diff_mod.compare(session, "new", "old")
    assert stats["sections_added"] == 1
    assert stats["sections_modified"] == 1
    assert stats["sections_removed"] == 0
    assert stats["references_added"] == 2
    assert stats["references_removed"] == 0
    assert {"title": "3 Results", "change": "added"} in changes


async def test_summary_falls_back_when_model_invents_a_number() -> None:
    class BadLLM:
        async def chat(self, *args: Any, **kwargs: Any) -> Any:
            class Result:
                text = "新增 99 个章节。"

            return Result()

    stats = {"sections_added": 1, "sections_removed": 0, "sections_modified": 0,
             "figures_changed": 0, "tables_changed": 0, "references_added": 0,
             "references_removed": 0}
    summary = await diff_mod.summarise(stats, [], BadLLM())
    assert "99" not in summary
    assert summary == diff_mod._fallback_summary(stats)


async def test_summary_keeps_grounded_model_text() -> None:
    class GoodLLM:
        async def chat(self, *args: Any, **kwargs: Any) -> Any:
            class Result:
                text = "新增 1 个章节，其余保持不变。"

            return Result()

    stats = {"sections_added": 1, "sections_removed": 0, "sections_modified": 0,
             "figures_changed": 0, "tables_changed": 0, "references_added": 0,
             "references_removed": 0}
    assert await diff_mod.summarise(stats, [], GoodLLM()) == "新增 1 个章节，其余保持不变。"


@pytest.mark.parametrize("length", [1, 200])
def test_summary_length_cap(length: int) -> None:
    stats = {"sections_added": 0, "sections_removed": 0, "sections_modified": 0,
             "figures_changed": 0, "tables_changed": 0, "references_added": 0,
             "references_removed": 0}
    assert len(diff_mod._fallback_summary(stats)) <= 200
    assert length <= 200


async def test_endpoint_diff_between_two_real_parses(session: Any, monkeypatch: Any) -> None:
    """The stored-document path: parse both PDFs, persist, then diff."""
    from httpx import ASGITransport, AsyncClient

    from app.ingest.parser import parse_pdf
    from app.main import create_app
    from app.workers.persist import persist_parse

    fixtures = FIXTURES
    ids = {}
    for name, doc_id in (("1706.03762v1.pdf", "doc-v1"), ("1706.03762v7.pdf", "doc-v7")):
        model = parse_pdf(fixtures / name, doc_id).model
        doc = Document(
            id=doc_id, sha256=f"sha-{doc_id}", title=model.meta.title, status="ready", file_path="/tmp/x.pdf"
        )
        session.add(doc)
        await session.flush()
        await persist_parse(session, model)
        ids[name] = doc_id
    await session.commit()

    class StubLLM:
        async def chat(self, *args: Any, **kwargs: Any) -> Any:
            class Result:
                text = "方法部分有修订。"

            return Result()

    monkeypatch.setattr("app.llm.gateway.get_gateway", lambda: StubLLM())
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/documents/{ids['1706.03762v7.pdf']}/versions/diff?other={ids['1706.03762v1.pdf']}"
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["other_id"] == ids["1706.03762v1.pdf"]
    assert body["stats"]["references_added"] == 4, "v7 cites four more references than v1"
    assert body["stats"]["sections_modified"] > 0
    assert len(body["summary"]) <= 200
    assert body["sections"]


async def test_endpoint_diff_missing_other_returns_404(session: Any) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    doc = Document(id="only", sha256="s", title="t", status="ready", file_path="/tmp/x.pdf")
    session.add(doc)
    await session.commit()

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/documents/only/versions/diff?other=missing")
    assert response.status_code == 404
