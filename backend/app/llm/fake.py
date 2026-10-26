"""Deterministic stand-in for tests (01 §6).

Unit tests never reach a real provider.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, TypeVar

from pydantic import BaseModel

from .types import ChatResult

TModel = TypeVar("TModel", bound=BaseModel)


class FakeLLM:
    """Returns canned text; records every call for assertions."""

    def __init__(
        self,
        reply: str = "ok",
        *,
        schema_reply: dict[str, Any] | None = None,
        fail_times: int = 0,
    ) -> None:
        self.reply = reply
        self.schema_reply = schema_reply
        self.fail_times = fail_times
        self.calls: list[dict[str, Any]] = []

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        tier: str = "fast",
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        stream: bool = False,
        tools: list[dict[str, Any]] | None = None,
        cache_prefix: str | None = None,
    ) -> ChatResult | AsyncIterator[str]:
        self.calls.append(
            {
                "messages": messages,
                "tier": tier,
                "json_schema": json_schema,
                "temperature": temperature,
                "stream": stream,
                "tools": tools,
                "cache_prefix": cache_prefix,
            }
        )
        if self.fail_times > 0:
            self.fail_times -= 1
            from .errors import LLMUnavailable

            raise LLMUnavailable("fake failure")
        if stream:
            return self._stream_text()
        text = self.reply
        if json_schema is not None and self.schema_reply is not None:
            text = json.dumps(self.schema_reply, ensure_ascii=False)
        return ChatResult(text=text, model="fake", prompt_tokens=1, completion_tokens=1)

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        schema: type[TModel],
        *,
        tier: str = "fast",
        temperature: float = 0.0,
        cache_prefix: str | None = None,
    ) -> TModel:
        result = await self.chat(
            messages, tier=tier, json_schema=schema.model_json_schema(), temperature=temperature
        )
        assert isinstance(result, ChatResult)
        return schema.model_validate_json(result.text)

    async def vision(
        self, image_bytes: bytes, prompt: str, *, json_schema: dict[str, Any] | None = None
    ) -> str:
        self.calls.append({"vision": True, "prompt": prompt, "size": len(image_bytes)})
        return self.reply

    async def close(self) -> None:
        return None

    async def _stream_text(self) -> AsyncIterator[str]:
        for token in self.reply.split(" "):
            yield token + " "
