"""Response cache for the LLM gateway.

Keys are derived from the resolved model, messages, schema and sampling params,
so an identical request never reaches the provider twice (H06, H08).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import OrderedDict
from typing import Any, Protocol

from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


def cache_key(model: str, messages: list[dict[str, str]], extra: dict[str, Any]) -> str:
    blob = json.dumps(
        {"model": model, "messages": messages, "extra": extra},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class CacheBackend(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl_s: int) -> None: ...
    async def close(self) -> None: ...


class MemoryCache:
    """Bounded TTL cache used when Redis is not configured (and in tests)."""

    def __init__(self, max_entries: int = 512) -> None:
        self._data: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._max = max_entries

    async def get(self, key: str) -> str | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at < time.time():
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return value

    async def set(self, key: str, value: str, ttl_s: int) -> None:
        self._data[key] = (time.time() + ttl_s, value)
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    async def close(self) -> None:
        self._data.clear()


class RedisCache:
    """Redis-backed cache that degrades to memory instead of failing a call (H08).

    Redis is optional infrastructure: if it is down the request must still reach
    the provider, so connection errors count as a miss and repeated failures
    switch the backend to `MemoryCache` for the rest of the process.
    """

    MAX_FAILURES = 3

    def __init__(self, url: str, prefix: str = "llm:") -> None:
        from redis.asyncio import Redis

        self._client = Redis.from_url(url, decode_responses=True)
        self._prefix = prefix
        self._failures = 0
        self._fallback: MemoryCache | None = None

    def _degrade(self, exc: Exception) -> None:
        self._failures += 1
        logger.warning("llm cache redis error (%s/%s): %s", self._failures, self.MAX_FAILURES, exc)
        if self._failures >= self.MAX_FAILURES and self._fallback is None:
            logger.warning("llm cache switched to memory after repeated redis errors")
            self._fallback = MemoryCache()

    async def get(self, key: str) -> str | None:
        if self._fallback is not None:
            return await self._fallback.get(key)
        try:
            value = await self._client.get(self._prefix + key)
        except (RedisError, OSError) as exc:
            self._degrade(exc)
            return None
        return value if isinstance(value, str) else None

    async def set(self, key: str, value: str, ttl_s: int) -> None:
        if self._fallback is not None:
            await self._fallback.set(key, value, ttl_s)
            return
        try:
            await self._client.set(self._prefix + key, value, ex=ttl_s)
        except (RedisError, OSError) as exc:
            self._degrade(exc)

    async def close(self) -> None:
        try:
            await self._client.aclose()
        except (RedisError, OSError) as exc:  # pragma: no cover - shutdown path
            logger.debug("llm cache close skipped: %s", exc)
