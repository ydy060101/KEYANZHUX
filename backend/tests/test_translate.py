"""T4.1/T4.2: selection translation, placeholder protection, document jobs.

The acceptance numbers (first-token latency, LaTeX identical after a real
translation) are measured by `tools/check_translation.py`; these tests pin the
mechanics with deterministic doubles: formulas and code survive a model that
drops a placeholder, the stream never shows half a marker, and a re-run of the
document job reuses every cached block.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.llm.types import ChatResult
from app.models.orm import Block, Document, Translation
from app.translate.protect import hold_point, integrity, protect, restore, split_segments
from app.translate.service import cache_key, stream_translation, translate_document, translate_text

SOURCE = "We set $d_{model}=512$ and `x = 1`; see [12]."


class PlaceholderGateway:
    """Returns a Chinese prefix plus every placeholder it was given."""

    def __init__(self, *, drop: str | None = None) -> None:
        self.drop = drop
        self.calls: list[dict[str, Any]] = []

    async def chat(self, messages: list[dict[str, str]], *, stream: bool = False, **kwargs: Any) -> ChatResult:
        self.calls.append({"messages": messages, "stream": stream, **kwargs})
        text = messages[-1]["content"]
        markers = re.findall(r"⟦\d+⟧", text)
        if self.drop is not None:
            markers = [marker for marker in markers if marker != self.drop]
        text = "译文" + "".join(markers)
        if stream:

            async def gen() -> AsyncIterator[str]:
                for token in text.split(" "):
                    yield token

            return gen()
        return ChatResult(text=text, model="fake", prompt_tokens=1, completion_tokens=1)


class ChunkGateway:
    """Streams exactly the chunks it is given, to test the hold-back."""

    def __init__(self, chunks: list[str]) -> None:
        self.chunks = chunks

    async def chat(self, messages: list[dict[str, str]], *, stream: bool = False, **kwargs: Any) -> Any:
        async def gen() -> AsyncIterator[str]:
            for chunk in self.chunks:
                yield chunk

        return gen()


def test_protect_masks_and_restores_every_span() -> None:
    protected = protect(SOURCE)
    assert protected.items == ["$d_{model}=512$", "`x = 1`", "[12]"]
    assert "⟦0⟧" in protected.masked
    assert restore(protected.masked, protected.items) == SOURCE


def test_integrity_reports_dropped_and_repeated_placeholders() -> None:
    items = ["a", "b", "c"]
    missing, duplicated = integrity("⟦0⟧ ⟦0⟧ ⟦2⟧", items)
    assert missing == [1]
    assert duplicated == [0]


def test_segments_keep_protected_text_verbatim() -> None:
    segments = split_segments(SOURCE)
    assert "".join(chunk for chunk, _ in segments) == SOURCE
    assert [chunk for chunk, protected in segments if protected] == [
        "$d_{model}=512$",
        "`x = 1`",
        "[12]",
    ]


def test_hold_point_never_splits_a_placeholder() -> None:
    assert hold_point("译文⟦") == 2
    assert hold_point("译文⟦1") == 2
    assert hold_point("译文⟦1⟧") == 5
    assert hold_point("译文 ⟦1⟧ 结束") == 9


async def test_translation_keeps_formulas_byte_identical() -> None:
    gateway = PlaceholderGateway()
    text, repaired = await translate_text(SOURCE, "en2zh", gateway)
    assert repaired is False
    assert "$d_{model}=512$" in text
    assert "`x = 1`" in text
    assert "[12]" in text


async def test_a_dropped_placeholder_falls_back_to_segments() -> None:
    gateway = PlaceholderGateway(drop="⟦0⟧")
    text, repaired = await translate_text(SOURCE, "en2zh", gateway)
    assert repaired is True
    assert "$d_{model}=512$" in text, "the formula cannot be lost by the fallback"
    assert "`x = 1`" in text
    # One call for the masked text, then one per prose segment.
    assert len(gateway.calls) > 1


async def test_streaming_restores_before_emitting() -> None:
    text = "We set $d_{model}=512$."
    gateway = ChunkGateway(["译文 ", "⟦", "0", "⟧", "。"])
    events: list[tuple[str, dict[str, Any]]] = []
    async for event in stream_translation(text, "en2zh", gateway):
        events.append(event)
    tokens = [data["text"] for name, data in events if name == "token"]
    assert "".join(tokens) == "译文 $d_{model}=512$。"
    assert all("⟦" not in token or "⟧" in token for token in tokens)
    done = events[-1]
    assert done[0] == "done"
    assert done[1]["text"] == "译文 $d_{model}=512$。"
    assert done[1]["repaired"] is False
    assert done[1]["first_token_ms"] is not None


def _document(session: Any) -> Document:
    doc = Document(
        id="doc-translate",
        sha256="b" * 64,
        title="Translate me",
        status="ready",
        file_path="unused.pdf",
        page_count=1,
    )
    session.add(doc)
    session.add_all(
        [
            Block(
                doc_id=doc.id,
                id="b1_1",
                type="heading",
                page=1,
                bbox=[0, 0, 10, 10],
                reading_order=1,
                text="Introduction",
            ),
            Block(
                doc_id=doc.id,
                id="b1_2",
                type="paragraph",
                page=1,
                bbox=[0, 10, 10, 20],
                reading_order=2,
                text="We use $x=1$ and $y=2$.",
            ),
        ]
    )
    return doc


async def test_document_job_is_cached_and_keeps_formulas(session: Any) -> None:
    doc = _document(session)
    await session.commit()

    gateway = PlaceholderGateway()
    first = await translate_document(session, doc.id, "en2zh", gateway)
    assert first["translated"] == 2
    assert first["cached"] == 0

    rows = (await session.execute(select(Translation).where(Translation.doc_id == doc.id))).scalars().all()
    assert len(rows) == 2
    by_block = {row.block_id: row for row in rows}
    assert "$x=1$" in by_block["b1_2"].text
    assert by_block["b1_2"].cache_key == cache_key("We use $x=1$ and $y=2$.", "en2zh")

    calls = len(gateway.calls)
    second = await translate_document(session, doc.id, "en2zh", gateway)
    assert second["cached"] == 2
    assert second["translated"] == 0
    assert len(gateway.calls) == calls, "a cached block must not reach the model"


async def test_changed_source_text_invalidates_the_cache(session: Any) -> None:
    doc = _document(session)
    await session.commit()
    gateway = PlaceholderGateway()
    await translate_document(session, doc.id, "en2zh", gateway)

    block = await session.get(Block, {"doc_id": doc.id, "id": "b1_2"})
    assert block is not None
    block.text = "We use $x=3$."
    await session.commit()

    again = await translate_document(session, doc.id, "en2zh", gateway)
    assert again["translated"] == 1
    assert again["cached"] == 1


@pytest.fixture
async def app_client() -> AsyncIterator[AsyncClient]:
    from app.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def test_selection_endpoint_streams_tokens_then_done(
    session: Any, app_client: AsyncClient, monkeypatch: Any
) -> None:
    import app.llm.gateway as gateway_module

    monkeypatch.setattr(gateway_module, "get_gateway", lambda: PlaceholderGateway())
    response = await app_client.post(
        "/api/v1/translate/selection",
        json={"text": SOURCE, "direction": "en2zh"},
    )
    assert response.status_code == 200, response.text
    assert "event: token" in response.text
    assert "event: done" in response.text
    assert "$d_{model}=512$" in response.text


async def test_selection_endpoint_reports_a_model_failure(
    session: Any, app_client: AsyncClient, monkeypatch: Any
) -> None:
    import app.llm.gateway as gateway_module
    from app.llm.errors import LLMUnavailable

    class Failing:
        async def chat(self, *args: Any, **kwargs: Any) -> Any:
            async def gen() -> AsyncIterator[str]:
                raise LLMUnavailable("down")
                yield ""

            return gen()

    monkeypatch.setattr(gateway_module, "get_gateway", Failing)
    response = await app_client.post("/api/v1/translate/selection", json={"text": "hello", "direction": "en2zh"})
    assert response.status_code == 200
    assert "event: error" in response.text
    assert "llm_unavailable" in response.text


async def test_document_endpoint_creates_a_job(session: Any, app_client: AsyncClient, monkeypatch: Any) -> None:
    import app.api.translate as translate_api

    doc = _document(session)
    await session.commit()
    queued: list[str] = []

    async def fake_enqueue(job_id: str) -> bool:
        queued.append(job_id)
        return True

    monkeypatch.setattr(translate_api.queue, "enqueue", fake_enqueue)
    response = await app_client.post(f"/api/v1/documents/{doc.id}/translate", json={"format": "md"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["job_id"]
    assert body["direction"] == "en2zh"
    assert queued == [body["job_id"]]

    job = (await session.execute(select(Translation))).scalars().all()
    assert job == [], "creating the job must not translate synchronously"


async def test_translation_endpoint_returns_aligned_blocks(session: Any, app_client: AsyncClient) -> None:
    doc = _document(session)
    session.add(
        Translation(
            id="doc-translate:b1_2:zh",
            doc_id=doc.id,
            block_id="b1_2",
            lang="zh",
            text="我们使用 $x=1$ 与 $y=2$。",
            cache_key=cache_key("We use $x=1$ and $y=2$.", "en2zh"),
        )
    )
    await session.commit()

    response = await app_client.get(f"/api/v1/documents/{doc.id}/translation")
    assert response.status_code == 200
    body = response.json()
    assert len(body["blocks"]) == 1
    assert body["blocks"][0]["block_id"] == "b1_2"
    assert body["blocks"][0]["original"].startswith("We use")
    assert body["blocks"][0]["translation"].startswith("我们使用")
    assert body["blocks"][0]["page"] == 1
