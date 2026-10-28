"""T7.4: Chinese → English academic translation.

The deterministic double here behaves like a cooperative translator: it
returns the Latin terms and protected placeholders it was given, and can be
told to drop one term until the strict retry quotes it back. That pins
chunking, formula/citation preservation, term repair and memoisation without
a model in the loop; `tools/check_academic_translation.py` checks the real
register and terminology.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.llm.types import ChatResult
from app.translate.academic import (
    MAX_INPUT_CHARS,
    chunk_text,
    clear_cache,
    missing_terms,
    translate_academic,
)
from app.translate.glossary import Entry, Glossary

SOURCE = "本文提出 Transformer 与 RAG 方法，见 $E=mc^2$ 和 [12]，BLEU 提升 3.5。"


def _body(messages: list[dict[str, str]]) -> str:
    match = re.search(r"<<<UNTRUSTED_DATA\n(.*?)\nUNTRUSTED_DATA>>>", messages[-1]["content"], re.S)
    return match.group(1) if match else messages[-1]["content"]


class TermGateway:
    """Echoes Latin terms and placeholders; can hide a term until told not to."""

    def __init__(self, *, drop: set[str] | None = None) -> None:
        self.drop = drop or set()
        self.calls: list[list[dict[str, str]]] = []

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> ChatResult:
        self.calls.append(messages)
        body = _body(messages)
        strict = "must appear verbatim" in messages[0]["content"]
        terms = list(dict.fromkeys(match.group(0) for match in re.finditer(r"[A-Za-z][A-Za-z0-9+#_.\-]{2,}", body)))
        if not strict:
            terms = [term for term in terms if term not in self.drop]
        markers = re.findall(r"⟦\d+⟧", body)
        text = "We propose " + " ".join(terms) + " with the reported gain. " + " ".join(markers)
        return ChatResult(text=text.strip(), model="fake", prompt_tokens=1, completion_tokens=1)


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    clear_cache()
    yield
    clear_cache()


def test_chunk_text_keeps_paragraphs_and_respects_the_limit() -> None:
    text = "第一段，RAG 方法。\n\n" + "第二段。" * 700
    chunks = chunk_text(text, limit=200)
    assert len(chunks) > 1
    assert all(len(chunk) <= 200 for chunk in chunks)
    assert chunks[0].endswith("。")

    short = chunk_text("甲。\n\n乙。", limit=200)
    assert short == ["甲。\n\n乙。"]


def test_chunking_never_splits_a_formula_or_a_term() -> None:
    formula = "前" * 47 + "$x$" + "后" * 80
    parts = chunk_text(formula, limit=49)
    assert "".join(parts) == formula
    assert all(part.count("$") % 2 == 0 for part in parts)

    named = "前" * 48 + "Transformer" + "后" * 20
    named_parts = chunk_text(named, limit=50)
    assert any("Transformer" in part for part in named_parts)
    assert "".join(named_parts) == named


def test_missing_terms_reports_only_lost_latin_terms() -> None:
    assert missing_terms("使用 RAG 与 GPT-4 和 BLEU", "uses RAG and BLEU") == ["GPT-4"]
    assert missing_terms("使用 RAG", "uses RAG") == []


async def test_academic_translation_keeps_formulas_citations_and_terms() -> None:
    gateway = TermGateway()
    result = await translate_academic(SOURCE, gateway)

    assert result.cached is False
    assert "$E=mc^2$" in result.text
    assert "[12]" in result.text
    for term in ("Transformer", "RAG", "BLEU"):
        assert term in result.text
    assert len(gateway.calls) == 1


async def test_a_lost_term_triggers_one_strict_retry() -> None:
    gateway = TermGateway(drop={"RAG"})
    result = await translate_academic(SOURCE, gateway)

    assert "RAG" in result.text
    assert len(gateway.calls) == 2
    assert "must appear verbatim" not in gateway.calls[0][0]["content"]
    assert "RAG" in gateway.calls[1][0]["content"]


async def test_long_text_is_chunked_concurrently_and_joined() -> None:
    text = "本文提出 RAG 方法。\n\n" + "实验结果显著。" * 400
    gateway = TermGateway()
    result = await translate_academic(text, gateway)

    chunks = chunk_text(text)
    assert len(chunks) > 1
    assert len(gateway.calls) == len(chunks)
    assert result.text.count("\n\n") == len(chunks) - 1
    assert "RAG" in result.text


async def test_second_identical_request_returns_the_cache() -> None:
    gateway = TermGateway()
    first = await translate_academic(SOURCE, gateway)
    calls = len(gateway.calls)
    second = await translate_academic(SOURCE, gateway)

    assert first.cached is False
    assert second.cached is True
    assert second.text == first.text
    assert len(gateway.calls) == calls


async def test_glossary_reaches_the_prompt_and_changes_the_cache_key() -> None:
    gateway = TermGateway()
    first_terms = Glossary(version=1, entries=(Entry("RAG", "检索增强生成"),))
    first = await translate_academic(SOURCE, gateway, glossary=first_terms)
    assert first.cached is False
    assert any("RAG => 检索增强生成" in messages[0]["content"] for messages in gateway.calls)

    calls = len(gateway.calls)
    again = await translate_academic(SOURCE, gateway, glossary=first_terms)
    assert again.cached is True
    assert len(gateway.calls) == calls

    edited_terms = Glossary(version=2, entries=(Entry("RAG", "RAG 方法"),))
    edited = await translate_academic(SOURCE, gateway, glossary=edited_terms)
    assert edited.cached is False
    assert len(gateway.calls) == calls + 1
    assert any("RAG => RAG 方法" in messages[0]["content"] for messages in gateway.calls[calls:])


async def test_empty_and_overlong_text_are_handled_without_calls() -> None:
    gateway = TermGateway()
    empty = await translate_academic("   ", gateway)
    assert empty.text == ""
    assert gateway.calls == []

    with pytest.raises(ValueError):
        await translate_academic("中" * (MAX_INPUT_CHARS + 1), gateway)
    assert gateway.calls == []


@pytest.fixture
async def app_client() -> AsyncIterator[AsyncClient]:
    from app.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def test_zh2en_endpoint_returns_translation_then_cached(app_client: AsyncClient, monkeypatch: Any) -> None:
    import app.llm.gateway as gateway_module

    monkeypatch.setattr(gateway_module, "get_gateway", lambda: TermGateway())
    payload = {"text": "本文提出 RAG 方法。"}
    first = await app_client.post("/api/v1/translate/zh2en", json=payload)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["direction"] == "zh2en"
    assert body["cached"] is False
    assert "RAG" in body["text"]

    second = await app_client.post("/api/v1/translate/zh2en", json=payload)
    assert second.status_code == 200
    assert second.json()["cached"] is True


async def test_zh2en_endpoint_rejects_empty_and_reverse_direction(app_client: AsyncClient, monkeypatch: Any) -> None:
    import app.llm.gateway as gateway_module

    monkeypatch.setattr(gateway_module, "get_gateway", lambda: TermGateway())
    empty = await app_client.post("/api/v1/translate/zh2en", json={"text": "   "})
    assert empty.status_code == 400
    assert empty.json()["error"]["code"] == "invalid_request"

    reverse = await app_client.post("/api/v1/translate/zh2en", json={"text": "hello", "direction": "en2zh"})
    assert reverse.status_code == 400
    assert reverse.json()["error"]["detail"]["direction"] == "en2zh"


async def test_zh2en_endpoint_reports_an_unknown_block(app_client: AsyncClient, session: Any) -> None:
    response = await app_client.post("/api/v1/translate/zh2en", json={"text": "本文提出 RAG。", "block_id": "missing"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_zh2en_endpoint_reports_a_model_failure(app_client: AsyncClient, monkeypatch: Any) -> None:
    import app.llm.gateway as gateway_module
    from app.llm.errors import LLMUnavailable

    class Failing:
        async def chat(self, *args: Any, **kwargs: Any) -> Any:
            raise LLMUnavailable("down")

    monkeypatch.setattr(gateway_module, "get_gateway", Failing)
    response = await app_client.post("/api/v1/translate/zh2en", json={"text": "本文提出 RAG。"})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "llm_unavailable"


async def test_zh2en_endpoint_wraps_validation_errors(app_client: AsyncClient) -> None:
    response = await app_client.post("/api/v1/translate/zh2en", json={"text": "中" * (MAX_INPUT_CHARS + 1)})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
