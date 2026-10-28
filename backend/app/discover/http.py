"""Whitelisted outbound HTTP for discovery (H08, H09).

Every external call goes through this module so three rules hold everywhere:

  * **the host is on H09's list** — checked before the request *and* on the
    final URL after redirects, because a whitelisted host can redirect to
    `169.254.169.254` or to an arbitrary site;
  * **timeouts, retries and a per-host rate limit** — 30 s per attempt, three
    attempts with exponential backoff, and a minimum interval between calls to
    the same API (Semantic Scholar answers 429 quickly otherwise);
  * **results are cached** — the same query within ten minutes does not hit
    the network again, which also keeps the demo reproducible (H06).

Failures are raised as :class:`SourceUnavailable`; the caller degrades per
source rather than failing the whole search (H08).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from ..errors import AppError, InvalidRequest

logger = logging.getLogger(__name__)

ALLOWED_HOSTS = {
    "arxiv.org",
    "export.arxiv.org",
    "api.semanticscholar.org",
    "api.crossref.org",
    "api.openalex.org",
    "api.github.com",
    "github.com",
}

CACHE_TTL_S = 600.0
CACHE_MAX = 128
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024

# Semantic Scholar's unauthenticated tier is the strictest of the four.
_MIN_INTERVAL = {
    "api.semanticscholar.org": 1.2,
    "api.crossref.org": 0.5,
    "api.openalex.org": 0.2,
    "export.arxiv.org": 0.5,
}


class SourceUnavailable(AppError):
    """One external source failed; the search continues with the others."""

    status_code = 502

    def __init__(self, source: str, reason: str) -> None:
        super().__init__(f"{source} 暂时不可用：{reason}", code="source_unavailable")
        self.source = source
        self.reason = reason


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def check_url(url: str) -> None:
    """Reject anything outside H09's whitelist before it is requested."""
    scheme = urlparse(url).scheme.lower()
    host = host_of(url)
    if scheme not in {"http", "https"} or host not in ALLOWED_HOSTS:
        raise InvalidRequest(
            "只允许从白名单域名下载",
            code="domain_not_allowed",
            detail={"url": url, "host": host},
        )


def safe_pdf_url(url: str | None) -> str | None:
    """The URL when we could actually download it, else None.

    Sources advertise PDFs on their own domains (`doi.org`, publisher sites).
    Handing such a URL to the UI would offer an import the downloader must
    refuse, so the hit keeps its metadata but reports no PDF (H09).
    """
    if not url:
        return None
    try:
        check_url(url)
    except InvalidRequest:
        return None
    return url


class SafeClient:
    def __init__(self, *, timeout_s: float = 30.0, retries: int = 3) -> None:
        self._timeout = timeout_s
        self._retries = retries
        self._cache: dict[str, tuple[float, bytes]] = {}
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
                headers={"User-Agent": "research-agent/0.1 (academic use)"},
            )
        return self._client

    async def _pace(self, host: str) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            interval = _MIN_INTERVAL.get(host, 0.0)
            if interval:
                wait = self._last.get(host, 0.0) + interval - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
            self._last[host] = time.monotonic()

    async def get(self, url: str, *, source: str, params: dict[str, Any] | None = None) -> bytes:
        check_url(url)
        key = f"{url}?{sorted((params or {}).items())}"
        cached = self._cache.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]

        client = await self._get_client()
        last: Exception | None = None
        for attempt in range(self._retries):
            await self._pace(host_of(url))
            try:
                response = await client.get(url, params=params)
                final_host = host_of(str(response.url))
                if final_host not in ALLOWED_HOSTS:
                    raise InvalidRequest(
                        "重定向到了白名单之外的地址",
                        code="domain_not_allowed",
                        detail={"url": str(response.url)},
                    )
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"{response.status_code}", request=response.request, response=response
                    )
                if 400 <= response.status_code < 500:
                    # A 404 is a wrong id, not a flaky source: retrying wastes
                    # the caller's time and the provider's quota.
                    raise SourceUnavailable(source, f"HTTP {response.status_code}")
                response.raise_for_status()
                body = response.content
                if len(self._cache) >= CACHE_MAX:
                    self._cache.clear()
                self._cache[key] = (time.monotonic() + CACHE_TTL_S, body)
                return body
            except InvalidRequest:
                raise
            except (httpx.TimeoutException, httpx.HTTPError) as exc:
                last = exc
                logger.warning("discover fetch %s attempt %d failed: %s", source, attempt + 1, exc)
                if attempt < self._retries - 1:
                    await asyncio.sleep(min(2**attempt, 8))
        raise SourceUnavailable(source, str(last) if last else "unknown error")

    async def download(self, url: str, *, source: str) -> bytes:
        """Stream a PDF, refusing a body larger than the upload limit.

        Retried like `get`: a dropped connection halfway through a 2 MB paper
        should not fail an import that would have succeeded on the next try.
        """
        check_url(url)
        last: Exception | None = None
        for attempt in range(self._retries):
            try:
                return await self._download_once(url, source)
            except InvalidRequest:
                raise
            except (httpx.TimeoutException, httpx.HTTPError) as exc:
                last = exc
                logger.warning("discover download %s attempt %d failed: %s", source, attempt + 1, exc)
                if attempt < self._retries - 1:
                    await asyncio.sleep(min(2**attempt, 8))
        raise SourceUnavailable(source, str(last) if last else "unknown error")

    async def _download_once(self, url: str, source: str) -> bytes:
        client = await self._get_client()
        await self._pace(host_of(url))
        async with client.stream("GET", url) as response:
            final_host = host_of(str(response.url))
            if final_host not in ALLOWED_HOSTS:
                raise InvalidRequest(
                    "重定向到了白名单之外的地址",
                    code="domain_not_allowed",
                    detail={"url": str(response.url)},
                )
            if 400 <= response.status_code < 500:
                raise SourceUnavailable(source, f"HTTP {response.status_code}")
            response.raise_for_status()
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_DOWNLOAD_BYTES:
                    raise InvalidRequest("文件超过 200MB 上限", code="file_too_large")
                chunks.append(chunk)
            return b"".join(chunks)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


_client: SafeClient | None = None


def get_client() -> SafeClient:
    global _client
    if _client is None:
        _client = SafeClient()
    return _client
