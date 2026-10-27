"""Shared corpus and stub embedder for the retrieval tests (T3.2).

Kept out of the test modules so each stays under H14's 400-line limit, and
because the golden set is the same one `tools/check_retrieval.py` measures with
the real models — a divergence between the two would make the unit result and
the acceptance number describe different questions.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import numpy as np

from app.models.orm import Chunk, Document
from app.rag.chunk import ChunkDraft
from app.rag.embedding import Embedder

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "pdf"
PAPER = "1706.03762v1.pdf"
BERT = "1810.04805_bert.pdf"

# (question, needle that must appear in the text of at least one returned chunk)
# The needles are quoted from the fixture's own text, not guessed: "warmup_steps
# = 4000" is on page 7 of Attention v1, "h = 8" is in §3.2.2, and so on. Each
# expectation is checked against the returned text rather than a hard-coded
# chunk id, so re-chunking the paper does not invalidate the test and the test
# cannot be satisfied by a lookup table (H05).
GOLDEN: list[tuple[str, str]] = [
    ("How many warmup steps does the learning rate schedule use?", "warmup_steps = 4000"),
    ("What optimizer and beta values were used for training?", "β2 = 0.98"),
    ("How many attention heads does the base model use?", "h = 8"),
    ("What dropout rate was used for the base model?", "Pdrop = 0.1"),
    ("How many identical layers are in the encoder?", "stack of N = 6 identical layers"),
    ("What is the dimension of the model embeddings?", "dmodel = 512"),
    ("How is positional information injected into the model?", "positional encodings"),
    ("What BLEU score did the big model reach on English-to-French?", "41.0"),
]


class BagOfWordsEmbedder(Embedder):
    """A deterministic lexical stand-in for bge-m3.

    Each token is hashed into one of `dim` buckets and the vector is
    L2-normalised, which is the crudest thing that still behaves like an
    embedding: texts sharing vocabulary land near each other, and texts that do
    not land far apart. It is deliberately *not* the same signal as BM25
    (`ts_rank_cd` weighs proximity and rarity; this only weighs presence), so a
    fusion test that passes here is not passing by accident.
    """

    def __init__(self, *, dim: int = 1024) -> None:
        super().__init__(model_name="stub-bow")
        self._dim = dim
        self._model = object()

    def _load(self) -> Any:  # pragma: no cover - never called
        return self._model

    def _encode(self, texts: list[str]) -> np.ndarray:
        rows = np.zeros((len(texts), self._dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in re.findall(r"[a-z0-9]+", text.lower()):
                bucket = int(hashlib.md5(token.encode()).hexdigest()[:8], 16) % self._dim
                rows[row, bucket] += 1.0
        norms = np.linalg.norm(rows, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        return np.asarray(rows / norms, dtype=np.float32)

    async def rerank(self, query: str, documents: list[str]) -> list[float] | None:
        """No cross-encoder: the stub reports the reranker as unavailable.

        Returning None is the H08 path — the pipeline must fall back to the
        fused order — which keeps the recall test honest about which stage did
        the work. The rerank stage itself is tested with its own scorer.
        """
        return None


class MissingEmbedder(BagOfWordsEmbedder):
    """An embedder whose model cannot load (H08's degraded path)."""

    def __init__(self) -> None:
        super().__init__()
        self._model = None
        self._load_error = "no weights"


async def load_document(session: Any, name: str, doc_id: str, chunks: list[ChunkDraft]) -> str:
    """Persist one document's chunks, with their stub vectors."""
    session.add(
        Document(
            id=doc_id,
            sha256=doc_id.ljust(64, "0")[:64],
            title=name,
            status="ready",
            file_path="x",
        )
    )
    embedder = BagOfWordsEmbedder()
    vectors = await embedder.embed([draft.text for draft in chunks])
    assert vectors is not None
    for draft, vector in zip(chunks, vectors, strict=True):
        session.add(
            Chunk(
                id=f"{doc_id}:{draft.block_ids[0]}",
                doc_id=doc_id,
                block_ids=list(draft.block_ids),
                section_id=draft.section_id,
                page_start=draft.page_start,
                page_end=draft.page_end,
                text=draft.text,
                embedding=[float(x) for x in vector],
            )
        )
    await session.commit()
    return doc_id


def bert_chunks() -> list[ChunkDraft]:
    """A small second corpus for the scope tests.

    Parsing a second PDF would double the fixture cost for tests that only need
    a chunk belonging to another document. The text is real BERT prose so the
    lexical retriever behaves normally.
    """
    return [
        ChunkDraft(
            block_ids=["b1_1", "b1_2"],
            section_id="h1",
            page_start=1,
            page_end=1,
            text=(
                "We introduce a new language representation model called BERT, which stands for "
                "Bidirectional Encoder Representations from Transformers. BERT is designed to "
                "pre-train deep bidirectional representations from unlabeled text."
            ),
        ),
        ChunkDraft(
            block_ids=["b2_1"],
            section_id="h2",
            page_start=2,
            page_end=2,
            text=(
                "The masked language model randomly masks some of the tokens from the input, and "
                "the objective is to predict the original vocabulary id of the masked word."
            ),
        ),
    ]
