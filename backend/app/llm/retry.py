"""Token-bucket rate limiter shared by all gateway calls."""

from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """Simple async token bucket. One instance per gateway."""

    def __init__(self, per_minute: int) -> None:
        self._rate = max(1, per_minute) / 60.0
        self._capacity = float(max(1, per_minute))
        self._tokens = self._capacity
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._last
                self._last = now
                self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self._rate
                await asyncio.sleep(wait)
