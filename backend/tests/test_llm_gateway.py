"""Gateway behaviour: retries, caching, schema validation (T0.3 acceptance)."""

from __future__ import annotations

import json

import httpx
import pytest
from app.llm.cache import MemoryCache
from app.llm.errors import LLMSchemaViolation, LLMUnavailable
from app.llm.gateway import LLMGateway
from pydantic import BaseModel


class Person(BaseModel):
    name: str
    age: int


def _gateway(handler, **kwargs) -> LLMGateway:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://test/v1")
    return LLMGateway(
        base_url="http://test/v1",
        api_key="k",
        models={"fast": "fake-fast", "strong": "fake-strong"},
        cache=kwargs.pop("cache", MemoryCache()),
        max_retries=kwargs.pop("max_retries", 3),
        client=client,
        **kwargs,
    )


def _ok(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "fake-fast",
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 5},
        },
    )


async def test_retries_on_timeout_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.TimeoutException("slow", request=request)
        return _ok("hello")

    gateway = _gateway(handler)
    result = await gateway.chat([{"role": "user", "content": "hi"}])
    assert result.text == "hello"
    assert calls["n"] == 3


async def test_gives_up_after_max_retries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow", request=request)

    gateway = _gateway(handler, max_retries=2)
    with pytest.raises(LLMUnavailable):
        await gateway.chat([{"role": "user", "content": "hi"}])


async def test_cache_hit_avoids_second_call() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _ok("cached-answer")

    gateway = _gateway(handler)
    first = await gateway.chat([{"role": "user", "content": "same"}])
    second = await gateway.chat([{"role": "user", "content": "same"}])
    assert first.text == second.text == "cached-answer"
    assert calls["n"] == 1
    assert second.cached is True


async def test_json_schema_retry_on_violation() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return _ok(json.dumps({"name": "x"}))
        return _ok(json.dumps({"name": "x", "age": 3}))

    gateway = _gateway(handler)
    person = await gateway.chat_json([{"role": "user", "content": "who"}], Person)
    assert person.age == 3
    assert calls["n"] == 2


async def test_json_schema_fails_after_retry() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _ok(json.dumps({"name": "x"}))

    gateway = _gateway(handler)
    with pytest.raises(LLMSchemaViolation):
        await gateway.chat_json([{"role": "user", "content": "who"}], Person)


async def test_system_guard_is_injected() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return _ok("ok")

    gateway = _gateway(handler)
    await gateway.chat([{"role": "user", "content": "hi"}])
    assert seen[0]["messages"][0]["role"] == "system"
    assert "UNTRUSTED_DATA" in seen[0]["messages"][0]["content"]
