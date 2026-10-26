"""Embedding service (01 §9).

bge-m3 runs locally through sentence-transformers; it is loaded once and reused.
When the model is unavailable the service reports `available == False` and
callers degrade — dedup falls back to L1/L2 and retrieval to BM25 only — rather
than the API failing (H08).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import numpy as np

from ..config import get_settings

logger = logging.getLogger(__name__)


class Embedder:
    """Lazily loaded sentence-transformer with a deterministic fallback."""

    def __init__(self, model_name: str, model_dir: str | None = None) -> None:
        self._model_name = model_name
        self._model_dir = model_dir
        self._model: Any = None
        self._load_error: str | None = None
        self._lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        return self._model is not None

    @property
    def load_error(self) -> str | None:
        return self._load_error

    async def _ensure_model(self) -> bool:
        if self._model is not None:
            return True
        if self._load_error is not None:
            return False
        async with self._lock:
            if self._model is not None:
                return True
            if self._load_error is not None:
                return False
            try:
                self._model = await asyncio.to_thread(self._load)
            except Exception as exc:  # pragma: no cover - depends on local weights
                self._load_error = f"{type(exc).__name__}: {exc}"
                logger.warning("embedding model unavailable: %s", self._load_error)
                return False
        return True

    def _load(self) -> Any:
        from sentence_transformers import SentenceTransformer

        kwargs: dict[str, Any] = {}
        if self._model_dir:
            kwargs["cache_folder"] = self._model_dir
        logger.info("loading embedding model %s", self._model_name)
        return SentenceTransformer(self._model_name, **kwargs)

    async def embed(self, texts: list[str], *, load: bool = True) -> np.ndarray | None:
        """L2-normalised vectors, or None when the model is unavailable.

        `load=False` returns None instead of paying the first-load cost, for
        callers on a latency budget (e.g. the upload response).
        """
        if not texts:
            return np.zeros((0, get_settings().embed_dim), dtype=np.float32)
        if not load and not self.available:
            return None
        if not await self._ensure_model():
            return None
        return await asyncio.to_thread(self._encode, texts)

    def _encode(self, texts: list[str]) -> np.ndarray:
        vectors = self._model.encode(
            texts,
            batch_size=16,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)

    async def embed_one(self, text: str) -> list[float] | None:
        matrix = await self.embed([text])
        if matrix is None or len(matrix) == 0:
            return None
        return [float(x) for x in matrix[0]]

    async def rerank(self, query: str, documents: list[str]) -> list[float] | None:
        """Cross-encoder scores; None when the reranker is unavailable."""
        if not documents:
            return []
        model = await self._ensure_reranker()
        if model is None:
            return None
        return await asyncio.to_thread(self._rerank_sync, model, query, documents)

    def _rerank_sync(self, model: Any, query: str, documents: list[str]) -> list[float]:
        pairs = [[query, doc] for doc in documents]
        scores = model.predict(pairs, show_progress_bar=False)
        return [float(s) for s in np.asarray(scores).reshape(-1)]

    async def _ensure_reranker(self) -> Any:
        if self._reranker is not None:
            return self._reranker
        if self._reranker_error is not None:
            return None
        async with self._lock:
            if self._reranker is not None:
                return self._reranker
            if self._reranker_error is not None:
                return None
            try:
                from sentence_transformers import CrossEncoder

                kwargs: dict[str, Any] = {}
                if self._model_dir:
                    kwargs["cache_folder"] = self._model_dir
                self._reranker = await asyncio.to_thread(
                    CrossEncoder, get_settings().rerank_model, **kwargs
                )
            except Exception as exc:  # pragma: no cover - depends on local weights
                self._reranker_error = f"{type(exc).__name__}: {exc}"
                logger.warning("reranker unavailable: %s", self._reranker_error)
                return None
        return self._reranker

    _reranker: Any = None
    _reranker_error: str | None = None


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        settings = get_settings()
        _embedder = Embedder(settings.embed_model, str(settings.model_dir))
    return _embedder


def set_embedder(embedder: Embedder | None) -> None:
    """Test hook."""
    global _embedder
    _embedder = embedder


def cosine(a: list[float] | np.ndarray, b: list[float] | np.ndarray) -> float:
    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom == 0.0:
        return 0.0
    return float(np.dot(va, vb) / denom)
