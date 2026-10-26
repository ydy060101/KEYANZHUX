"""The single LLM entry point (01 §6).

Business code passes a tier, never a model name or an API key. The gateway owns
timeouts, retries, rate limiting, caching, structured-output validation and
logging.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from ..config import get_settings
from .cache import CacheBackend, MemoryCache, RedisCache, cache_key
from .errors import FeatureDisabled, LLMRateLimited, LLMSchemaViolation, LLMTimeout, LLMUnavailable
from .retry import RateLimiter
from .safety import system_with_guard, wrap_data
from .types import ChatResult, Tier

logger = logging.getLogger(__name__)

TModel = TypeVar("TModel", bound=BaseModel)


class LLMGateway:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        models: dict[Tier, str],
        vision_enabled: bool = False,
        timeout_s: float = 30.0,
        max_retries: int = 3,
        cache: CacheBackend | None = None,
        cache_ttl_s: int = 86_400,
        rate_limit_per_min: int = 60,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._models = models
        self._vision_enabled = vision_enabled
        self._timeout = timeout_s
        self._max_retries = max_retries
        self._cache = cache
        self._cache_ttl = cache_ttl_s
        self._limiter = RateLimiter(rate_limit_per_min)
        self._client = client
        self._owns_client = client is None

    # -- public API --------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        tier: Tier = "fast",
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        stream: bool = False,
        tools: list[dict[str, Any]] | None = None,
        cache_prefix: str | None = None,
    ) -> ChatResult | AsyncIterator[str]:
        if stream:
            return self._stream(messages, tier=tier, temperature=temperature, cache_prefix=cache_prefix)
        return await self._complete(
            messages,
            tier=tier,
            json_schema=json_schema,
            temperature=temperature,
            tools=tools,
            cache_prefix=cache_prefix,
        )

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        schema: type[TModel],
        *,
        tier: Tier = "fast",
        temperature: float = 0.0,
        cache_prefix: str | None = None,
    ) -> TModel:
        """Structured output validated against ``schema``; one retry on violation."""
        json_schema = schema.model_json_schema()
        attempt_messages = list(messages)
        last_error: Exception | None = None
        for attempt in range(2):
            result = await self._complete(
                attempt_messages,
                tier=tier,
                json_schema=json_schema,
                temperature=temperature,
                tools=None,
                cache_prefix=cache_prefix,
            )
            assert isinstance(result, ChatResult)
            try:
                return schema.model_validate_json(_strip_fence(result.text))
            except ValidationError as exc:
                last_error = exc
                logger.warning("structured output invalid on attempt %s: %s", attempt + 1, exc)
                attempt_messages = [
                    *messages,
                    {"role": "assistant", "content": result.text},
                    {
                        "role": "user",
                        "content": (
                            "That response did not match the required JSON schema. "
                            f"Validation errors: {exc.errors()[:3]}. "
                            "Return only corrected JSON."
                        ),
                    },
                ]
        raise LLMSchemaViolation(f"structured output failed validation: {last_error}")

    async def vision(
        self, image_bytes: bytes, prompt: str, *, json_schema: dict[str, Any] | None = None
    ) -> str:
        if not self._vision_enabled:
            raise FeatureDisabled("vision is disabled (LLM_VISION_ENABLED=false)")
        import base64

        b64 = base64.b64encode(image_bytes).decode("ascii")
        payload_messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }
        ]
        result = await self._request(
            payload_messages,
            model=self._models["fast"],
            temperature=0.0,
            json_schema=json_schema,
            tools=None,
        )
        return result.text

    # -- internals ---------------------------------------------------------

    async def _complete(
        self,
        messages: list[dict[str, str]],
        *,
        tier: Tier,
        json_schema: dict[str, Any] | None,
        temperature: float,
        tools: list[dict[str, Any]] | None,
        cache_prefix: str | None,
    ) -> ChatResult:
        model = self._models[tier]
        # Fixed content first so the provider can reuse its prompt cache.
        prepared = list(messages)
        if cache_prefix:
            prepared = [{"role": "system", "content": cache_prefix}, *prepared]
        prepared = _apply_guard(prepared)

        key = None
        if self._cache is not None and temperature == 0.0:
            key = cache_key(
                model,
                prepared,
                {"schema": json_schema, "tools": tools, "temperature": temperature},
            )
            hit = await self._cache.get(key)
            if hit is not None:
                data = json.loads(hit)
                return ChatResult(**data, cached=True)

        result = await self._request(
            prepared, model=model, temperature=temperature, json_schema=json_schema, tools=tools
        )
        if key is not None and self._cache is not None:
            payload = json.dumps(
                {
                    "text": result.text,
                    "model": result.model,
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                    "latency_ms": result.latency_ms,
                }
            )
            await self._cache.set(key, payload, self._cache_ttl)
        return result

    async def _request(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float,
        json_schema: dict[str, Any] | None,
        tools: list[dict[str, Any]] | None,
    ) -> ChatResult:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_schema is not None:
            payload["response_format"] = {"type": "json_object"}
        if tools:
            payload["tools"] = tools

        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            await self._limiter.acquire()
            started = time.monotonic()
            try:
                client = await self._get_client()
                response = await client.post("/chat/completions", json=payload)
                elapsed_ms = (time.monotonic() - started) * 1000
                if response.status_code == 429:
                    raise LLMRateLimited(response.text[:200])
                if response.status_code >= 500:
                    raise LLMUnavailable(response.text[:200])
                response.raise_for_status()
                body = response.json()
                choice = body["choices"][0]
                usage = body.get("usage", {})
                result = ChatResult(
                    text=choice["message"].get("content") or "",
                    model=body.get("model", model),
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    latency_ms=elapsed_ms,
                )
                logger.info(
                    "llm_call model=%s tokens_in=%s tokens_out=%s ms=%.0f",
                    result.model,
                    result.prompt_tokens,
                    result.completion_tokens,
                    elapsed_ms,
                )
                return result
            except (httpx.TimeoutException, LLMTimeout) as exc:
                last_error = exc
                logger.warning("llm timeout on attempt %s: %s", attempt + 1, exc)
            except LLMRateLimited as exc:
                last_error = exc
                logger.warning("llm rate limited on attempt %s", attempt + 1)
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning("llm transport error on attempt %s: %s", attempt + 1, exc)
            except LLMUnavailable as exc:
                last_error = exc
                logger.warning("llm unavailable on attempt %s: %s", attempt + 1, exc)
            if attempt < self._max_retries - 1:
                await asyncio.sleep(min(2**attempt, 8))
        raise LLMUnavailable(f"LLM call failed after {self._max_retries} attempts: {last_error}")

    async def _stream(
        self,
        messages: list[dict[str, str]],
        *,
        tier: Tier,
        temperature: float,
        cache_prefix: str | None,
    ) -> AsyncIterator[str]:
        model = self._models[tier]
        prepared = list(messages)
        if cache_prefix:
            prepared = [{"role": "system", "content": cache_prefix}, *prepared]
        prepared = _apply_guard(prepared)
        payload = {
            "model": model,
            "messages": prepared,
            "temperature": temperature,
            "stream": True,
        }
        await self._limiter.acquire()
        client = await self._get_client()
        async with client.stream("POST", "/chat/completions", json=payload) as response:
            if response.status_code >= 400:
                body = await response.aread()
                raise LLMUnavailable(f"stream failed: {response.status_code} {body[:200]!r}")
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content")
                if content:
                    yield content

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"Content-Type": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            self._client = httpx.AsyncClient(
                base_url=self._base_url, timeout=self._timeout, headers=headers
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None
        if self._cache is not None:
            await self._cache.close()


def _apply_guard(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Ensure a system prompt exists and carries the injection guard."""
    out = list(messages)
    if out and out[0]["role"] == "system":
        out[0] = {"role": "system", "content": system_with_guard(out[0]["content"])}
    else:
        out.insert(0, {"role": "system", "content": system_with_guard("You are a research assistant.")})
    return out


def _strip_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


_gateway: LLMGateway | None = None


def get_gateway() -> LLMGateway:
    global _gateway
    if _gateway is None:
        settings = get_settings()
        cache: CacheBackend | None = None
        if settings.redis_url:
            try:
                cache = RedisCache(settings.redis_url)
            except Exception:  # pragma: no cover - falls back when Redis is absent
                logger.warning("redis unavailable, using in-memory LLM cache")
                cache = MemoryCache()
        else:
            cache = MemoryCache()
        _gateway = LLMGateway(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            models={"fast": settings.llm_fast, "strong": settings.llm_strong},
            vision_enabled=settings.llm_vision_enabled,
            timeout_s=settings.llm_timeout_s,
            max_retries=settings.llm_max_retries,
            cache=cache,
            cache_ttl_s=settings.llm_cache_ttl_s,
            rate_limit_per_min=settings.llm_rate_limit_per_min,
        )
    return _gateway


def set_gateway(gateway: LLMGateway | None) -> None:
    """Test hook so suites can inject FakeLLM."""
    global _gateway
    _gateway = gateway


__all__ = ["LLMGateway", "get_gateway", "set_gateway", "wrap_data"]
