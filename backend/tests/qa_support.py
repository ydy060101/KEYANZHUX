"""Corpus and doubles for the T3.3 QA tests.

The gateway double is deliberately prompt-aware: it finds the evidence block
holding a known needle and cites *that* number, instead of hard-coding "[1]".
Rank order depends on BM25 and would make a fixed marker test the retriever
rather than the anchor mapping. The real models are exercised by
`tools/check_qa.py`, which is the only place an external LLM is called (H15).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.llm.errors import LLMUnavailable
from app.llm.types import ChatResult
from app.models.orm import Document
from app.rag.chunk import ChunkDraft
from app.rag.index import write_index
from app.workers.persist import persist_parse
from retrieval_support import BagOfWordsEmbedder

DOC = "doc-transformer"
TITLE = "Attention Is All You Need"
GOLDEN_PATH = Path(__file__).with_name("golden_qa.json")

_BLOCK = re.compile(
    r"\[(\d+)\][^\n]*\n<<<UNTRUSTED_DATA\n(.*?)\nUNTRUSTED_DATA>>>",
    re.DOTALL,
)


async def load_qa_corpus(session: Any, model: Any, chunks: list[ChunkDraft]) -> None:
    """Persist the fixture document with blocks, chunks and sections.

    Blocks matter here and not in the retrieval tests: a citation's anchor is a
    `blocks` row, so a corpus without block rows would make every answer refuse
    for the wrong reason.
    """
    session.add(
        Document(
            id=DOC,
            sha256="a" * 64,
            title=TITLE,
            status="ready",
            page_count=model.page_count,
            file_path="fixture.pdf",
        )
    )
    await session.flush()
    await persist_parse(session, model)
    await write_index(session, DOC, model.blocks, model.outline, chunks)
    await session.commit()


class ScoredEmbedder(BagOfWordsEmbedder):
    """A stub whose reranker gives every candidate the same score.

    The value decides which side of `QA_MIN_SCORE` the pipeline sees; the
    ordering itself is the fused order, which is enough to test the gate.
    """

    def __init__(self, score: float) -> None:
        super().__init__()
        self._score = score

    async def rerank(self, query: str, documents: list[str]) -> list[float] | None:
        return [self._score] * len(documents)


class BaselineEmbedder(BagOfWordsEmbedder):
    """Reranker unavailable (H08's degraded path)."""


class QaGateway:
    """A gateway double whose reply can be derived from the prompt."""

    def __init__(
        self,
        answer: str | Callable[[str], str] = "NOT_FOUND",
        extraction: dict[str, Any] | Callable[[str], dict[str, Any]] | None = None,
        *,
        extraction_error: Exception | None = None,
    ) -> None:
        self._answer = answer
        self._extraction = extraction
        self._extraction_error = extraction_error
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
    ) -> ChatResult:
        self.calls.append({"kind": "chat", "messages": messages, "tier": tier})
        text = self._answer(messages[-1]["content"]) if callable(self._answer) else self._answer
        return ChatResult(text=text, model="fake", prompt_tokens=1, completion_tokens=1)

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        schema: Any,
        *,
        tier: str = "fast",
        temperature: float = 0.0,
        cache_prefix: str | None = None,
    ) -> Any:
        self.calls.append({"kind": "json", "messages": messages, "tier": tier})
        if self._extraction_error is not None:
            raise self._extraction_error
        prompt = messages[-1]["content"]
        payload = self._extraction(prompt) if callable(self._extraction) else self._extraction
        return schema.model_validate(payload or {"fields": []})


class FailingExtractionGateway(QaGateway):
    """Extraction is down; answering must still work (H08)."""

    def __init__(self, answer: str | Callable[[str], str]) -> None:
        super().__init__(answer, extraction_error=LLMUnavailable("extraction down"))


def evidence_number(prompt: str, needle: str) -> int:
    """The number of the evidence block whose text contains `needle`."""
    for match in _BLOCK.finditer(prompt):
        if needle in match.group(2):
            return int(match.group(1))
    raise AssertionError(f"no evidence block contains {needle!r}")


def load_golden() -> dict[str, Any]:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
