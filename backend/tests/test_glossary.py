"""T4.4: the reader's glossary, its version and its cache identity.

The acceptance requirement is one sentence — "repeated translation hits the
cache" — but it only holds if editing the glossary also breaks that cache.
These tests pin both halves with a deterministic gateway: unchanged terms
reuse every block; changed terms retranslate every affected block, and the
term mapping reaches the model's system prompt.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.llm.types import ChatResult
from app.models.orm import Block, Document, Translation
from app.translate import glossary as glossary_module
from app.translate.glossary import Entry, Glossary, load_glossary, save_glossary
from app.translate.service import cache_key, translate_document


class RecordingGateway:
    """Returns a fixed Chinese string and records every system prompt."""

    def __init__(self) -> None:
        self.systems: list[str] = []

    async def chat(self, messages: list[dict[str, str]], *, stream: bool = False, **kwargs: Any) -> ChatResult:
        self.systems.append(messages[0]["content"])
        if stream:

            async def gen() -> AsyncIterator[str]:
                yield "译文"

            return gen()
        return ChatResult(text="译文", model="fake", prompt_tokens=1, completion_tokens=1)


@pytest.fixture
def glossary_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(glossary_module, "_directory", lambda: tmp_path)
    return tmp_path


def test_glossary_is_per_user_and_versioned(glossary_dir: Path) -> None:
    empty = load_glossary("alice")
    assert empty.version == 0 and empty.entries == ()

    saved = save_glossary("alice", [{"source": " Transformer ", "target": " Transformer 模型 "}])
    assert saved.version == 1
    assert saved.entries == (Entry("Transformer", "Transformer 模型"),)
    assert load_glossary("alice").version == 1
    assert load_glossary("bob").version == 0

    same = save_glossary("alice", [{"source": "Transformer", "target": "Transformer 模型"}])
    assert same.version == 1, "an unchanged list must not invalidate the cache"

    deleted = save_glossary("alice", [])
    assert deleted.version == 2 and deleted.entries == ()
    assert load_glossary("alice").version == 2

    files = list(glossary_dir.glob("*.json"))
    assert len(files) == 1
    assert "alice" not in files[0].name, "the filename must not contain the user id"


def test_glossary_deduplicates_and_rejects_long_or_multiline_terms(glossary_dir: Path) -> None:
    saved = save_glossary(
        "default",
        [
            {"source": "attention", "target": "注意力"},
            {"source": "Attention", "target": "注意力机制"},
        ],
    )
    assert saved.entries == (Entry("Attention", "注意力机制"),)
    with pytest.raises(ValueError):
        save_glossary("default", [{"source": "x" * 200, "target": "y"}])
    with pytest.raises(ValueError):
        save_glossary("default", [{"source": "a\nb", "target": "y"}])


def test_only_terms_present_in_the_block_reach_the_prompt(glossary_dir: Path) -> None:
    glossary = Glossary(
        version=1,
        entries=(
            Entry("attention", "注意力"),
            Entry("BLEU", "BLEU 分数"),
            Entry("Transformer", "Transformer 模型"),
        ),
    )
    suffix = glossary.prompt_suffix("We study ATTENTION and nothing else.")
    assert "attention => 注意力" in suffix
    assert "BLEU" not in suffix
    assert "Transformer" not in suffix
    assert glossary.prompt_suffix("unrelated text") == ""


def test_cache_key_includes_the_glossary_version_and_content() -> None:
    plain = cache_key("some text", "en2zh")
    assert cache_key("some text", "en2zh", 0) == plain
    assert cache_key("some text", "en2zh", 1) != plain
    assert cache_key("some text", "en2zh", 2) != cache_key("some text", "en2zh", 1)
    # Two users can both be at version 1 with different terms; the rows are
    # shared, so the content fingerprint must distinguish them.
    assert cache_key("some text", "en2zh", 1, "a" * 16) != cache_key("some text", "en2zh", 1, "b" * 16)


def _document(session: Any) -> Document:
    doc = Document(
        id="doc-glossary",
        sha256="c" * 64,
        title="Glossary me",
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
                type="paragraph",
                page=1,
                bbox=[0, 0, 10, 10],
                reading_order=1,
                text="We study attention with a Transformer.",
            ),
            Block(
                doc_id=doc.id,
                id="b1_2",
                type="paragraph",
                page=1,
                bbox=[0, 10, 10, 20],
                reading_order=2,
                text="The dataset is small.",
            ),
        ]
    )
    return doc


async def test_document_reuses_cache_until_the_glossary_changes(session: Any) -> None:
    doc = _document(session)
    await session.commit()
    gateway = RecordingGateway()
    first_glossary = Glossary(version=1, entries=(Entry("attention", "注意力机制"),))

    first = await translate_document(session, doc.id, "en2zh", gateway, glossary=first_glossary)
    assert first["translated"] == 2
    assert first["cached"] == 0
    assert first["glossary_version"] == 1
    assert any("attention => 注意力机制" in system for system in gateway.systems)

    calls = len(gateway.systems)
    second = await translate_document(session, doc.id, "en2zh", gateway, glossary=first_glossary)
    assert second["cached"] == 2 and second["translated"] == 0
    assert len(gateway.systems) == calls, "a cached block must not reach the model"

    edited = Glossary(version=2, entries=(Entry("attention", "注意力"),))
    third = await translate_document(session, doc.id, "en2zh", gateway, glossary=edited)
    assert third["translated"] == 2 and third["cached"] == 0
    assert len(gateway.systems) == calls + 2
    assert any("attention => 注意力" in system for system in gateway.systems[calls:])

    # Same version, different list: another reader's rows cannot match.
    other_reader = Glossary(version=2, entries=(Entry("attention", "关注"),))
    fourth = await translate_document(session, doc.id, "en2zh", gateway, glossary=other_reader)
    assert fourth["translated"] == 2 and fourth["cached"] == 0

    rows = (await session.execute(select(Translation).where(Translation.doc_id == doc.id))).scalars().all()
    assert {row.cache_key for row in rows} == {
        cache_key("We study attention with a Transformer.", "en2zh", 2, other_reader.fingerprint()),
        cache_key("The dataset is small.", "en2zh", 2, other_reader.fingerprint()),
    }


@pytest.fixture
async def app_client() -> AsyncIterator[AsyncClient]:
    from app.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def test_glossary_endpoints_add_and_delete(glossary_dir: Path, app_client: AsyncClient) -> None:
    empty = await app_client.get("/api/v1/translate/glossary")
    assert empty.status_code == 200
    assert empty.json() == {"version": 0, "entries": [], "updated_at": None}

    added = await app_client.put(
        "/api/v1/translate/glossary",
        json={"entries": [{"source": " attention ", "target": " 注意力 "}]},
    )
    assert added.status_code == 200, added.text
    body = added.json()
    assert body["version"] == 1
    assert body["entries"] == [{"source": "attention", "target": "注意力"}]

    unchanged = await app_client.put(
        "/api/v1/translate/glossary",
        json={"entries": [{"source": "attention", "target": "注意力"}]},
    )
    assert unchanged.json()["version"] == 1

    removed = await app_client.put("/api/v1/translate/glossary", json={"entries": []})
    removed_body = removed.json()
    assert removed_body["version"] == 2
    assert removed_body["entries"] == []

    rejected = await app_client.put(
        "/api/v1/translate/glossary",
        json={"entries": [{"source": "a\nb", "target": "c"}]},
    )
    assert rejected.status_code == 422
    assert "error" in rejected.json()


async def test_selection_uses_the_users_glossary(glossary_dir: Path, app_client: AsyncClient, monkeypatch: Any) -> None:
    import app.llm.gateway as gateway_module

    save_glossary("default", [{"source": "attention", "target": "注意力机制"}])
    gateway = RecordingGateway()
    monkeypatch.setattr(gateway_module, "get_gateway", lambda: gateway)
    response = await app_client.post(
        "/api/v1/translate/selection",
        json={"text": "We study attention.", "direction": "en2zh"},
    )
    assert response.status_code == 200, response.text
    assert "event: done" in response.text
    assert any("attention => 注意力机制" in system for system in gateway.systems)
