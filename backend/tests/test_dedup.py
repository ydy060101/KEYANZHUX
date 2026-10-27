"""T1.4 acceptance: L1/L2/L3 dedup and the resolve action.

Case 3.1 from 04 §1: upload v7 first, then v1 — the second upload must be
flagged `same_paper_other_version` and must recommend keeping v7. Renaming the
file must not change the outcome (no filename heuristics).

L3 runs against a deterministic stub embedder so the test does not depend on
model weights being present.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from app.dedup import fingerprint
from app.dedup.service import Candidate, check, store_fingerprint
from app.models.orm import Document
from app.rag.embedding import Embedder


class StubEmbedder(Embedder):
    """Maps text to a vector by keyword presence, so similarity is predictable.

    Padded to the configured embedding dimension because the column is fixed
    at `EMBED_DIM`; only the first few components carry signal.
    """

    def __init__(self, topics: list[str] | None = None) -> None:
        super().__init__(model_name="stub")
        self.topics = topics or ["transformer", "bert", "gpt", "vision", "graph"]
        self._model = object()  # marks it available

    def _load(self) -> Any:  # pragma: no cover - never called
        return self._model

    def _encode(self, texts: list[str]) -> np.ndarray:
        from app.config import get_settings

        dim = get_settings().embed_dim
        out = []
        for text in texts:
            lowered = text.lower()
            vector = np.zeros(dim, dtype=np.float32)
            for index, topic in enumerate(self.topics):
                vector[index] = lowered.count(topic) + 0.01
            out.append(vector / np.linalg.norm(vector))
        return np.vstack(out)


class UnavailableEmbedder(Embedder):
    def __init__(self) -> None:
        super().__init__(model_name="missing")
        self._load_error = "no weights"

    def _load(self) -> Any:  # pragma: no cover - never called
        raise RuntimeError("no weights")


TRANSFORMER_TEXT = (
    "Attention Is All You Need. The dominant sequence transduction models are based on complex "
    "recurrent or convolutional neural networks. We propose the Transformer, based solely on "
    "attention mechanisms, dispensing with recurrence and convolutions entirely."
)
BERT_TEXT = (
    "BERT: Pre-training of Deep Bidirectional Transformers. We introduce a new language "
    "representation model called BERT, which stands for Bidirectional Encoder Representations "
    "from Transformers. Unlike recent language representation models, BERT is designed to "
    "pre-train deep bidirectional representations from unlabeled text."
)


async def _add_doc(
    session: Any,
    *,
    sha256: str,
    title: str,
    abstract: str,
    arxiv_id: str | None = None,
    version: str | None = None,
    body: str = "",
) -> Document:
    doc = Document(
        sha256=sha256,
        title=title,
        arxiv_id=arxiv_id,
        version=version,
        status="ready",
        file_path=f"/tmp/{sha256}.pdf",
    )
    session.add(doc)
    await session.flush()
    await store_fingerprint(
        session,
        doc.id,
        Candidate(sha256=sha256, arxiv_id=arxiv_id, version=version, title=title, abstract=abstract, body=body),
        embedder=StubEmbedder(),
    )
    return doc


def test_minhash_is_deterministic() -> None:
    a = fingerprint.signature(TRANSFORMER_TEXT)
    b = fingerprint.signature(TRANSFORMER_TEXT)
    assert a == b
    assert len(a) == fingerprint.NUM_PERM


def test_minhash_similar_texts_score_high() -> None:
    base = fingerprint.signature(TRANSFORMER_TEXT)
    near = fingerprint.signature(TRANSFORMER_TEXT + " One extra sentence at the end.")
    far = fingerprint.signature(BERT_TEXT)
    assert fingerprint.jaccard(base, near) > 0.6
    assert fingerprint.jaccard(base, far) < 0.2


async def test_l1_exact_duplicate(session: Any) -> None:
    doc = await _add_doc(session, sha256="a" * 64, title="Transformer", abstract=TRANSFORMER_TEXT)
    hit = await check(
        session,
        Candidate(sha256="a" * 64, arxiv_id=None, version=None, title="Renamed", abstract="", body=""),
        embedder=StubEmbedder(),
    )
    assert hit is not None
    assert hit.level == "exact_duplicate"
    assert hit.matched_doc_id == doc.id
    assert hit.suggestion == "keep_existing"


async def test_case_3_1_v7_then_v1(session: Any) -> None:
    """04 §1 case 3.1: v7 is in the library, v1 arrives second."""
    v7 = await _add_doc(
        session,
        sha256="b" * 64,
        title="Attention Is All You Need",
        abstract=TRANSFORMER_TEXT,
        arxiv_id="1706.03762",
        version="v7",
        body=TRANSFORMER_TEXT,
    )
    hit = await check(
        session,
        Candidate(
            sha256="c" * 64,
            arxiv_id="1706.03762",
            version="v1",
            title="Attention Is All You Need",
            abstract=TRANSFORMER_TEXT,
            body=TRANSFORMER_TEXT,
        ),
        embedder=StubEmbedder(),
    )
    assert hit is not None
    assert hit.level == "same_paper_other_version"
    assert hit.matched_doc_id == v7.id
    assert hit.existing_version == "v7"
    assert hit.new_version == "v1"
    assert hit.suggestion == "keep_existing"
    assert "较新" in hit.reason


async def test_renaming_does_not_change_the_verdict(session: Any) -> None:
    await _add_doc(
        session,
        sha256="d" * 64,
        title="Attention Is All You Need",
        abstract=TRANSFORMER_TEXT,
        arxiv_id="1706.03762",
        version="v7",
    )
    for name in ("paper.pdf", "totally_different_name.pdf", "x.pdf"):
        hit = await check(
            session,
            Candidate(
                sha256=f"{name}-hash",
                arxiv_id="1706.03762",
                version="v1",
                title=name,
                abstract="",
                body="",
            ),
            embedder=StubEmbedder(),
        )
        assert hit is not None and hit.level == "same_paper_other_version"


async def test_l3_content_duplicate(session: Any) -> None:
    await _add_doc(
        session,
        sha256="e" * 64,
        title="Attention Is All You Need",
        abstract=TRANSFORMER_TEXT,
        body=TRANSFORMER_TEXT,
    )
    hit = await check(
        session,
        Candidate(
            sha256="f" * 64,
            arxiv_id=None,
            version=None,
            title="Attention Is All You Need",
            abstract=TRANSFORMER_TEXT,
            body=TRANSFORMER_TEXT,
        ),
        embedder=StubEmbedder(),
    )
    assert hit is not None
    assert hit.level in {"content_duplicate", "possible_duplicate"}
    assert hit.similarity >= 0.85


async def test_l3_ignores_unrelated_documents(session: Any) -> None:
    await _add_doc(session, sha256="1" * 64, title="BERT", abstract=BERT_TEXT, body=BERT_TEXT)
    hit = await check(
        session,
        Candidate(
            sha256="2" * 64,
            arxiv_id=None,
            version=None,
            title="Attention Is All You Need",
            abstract=TRANSFORMER_TEXT,
            body=TRANSFORMER_TEXT,
        ),
        embedder=StubEmbedder(),
    )
    assert hit is None


async def test_l3_degrades_without_embeddings(session: Any) -> None:
    """Without the model, an identical-body upload still matches by MinHash."""
    await _add_doc(
        session,
        sha256="3" * 64,
        title="Attention Is All You Need",
        abstract=TRANSFORMER_TEXT,
        body=TRANSFORMER_TEXT,
    )
    hit = await check(
        session,
        Candidate(
            sha256="4" * 64,
            arxiv_id=None,
            version=None,
            title="Attention Is All You Need",
            abstract=TRANSFORMER_TEXT,
            body=TRANSFORMER_TEXT,
        ),
        embedder=UnavailableEmbedder(),
    )
    assert hit is not None
    assert hit.level == "content_duplicate"


async def test_exclude_self_on_reparse(session: Any) -> None:
    doc = await _add_doc(session, sha256="5" * 64, title="Transformer", abstract=TRANSFORMER_TEXT)
    hit = await check(
        session,
        Candidate(sha256="5" * 64, arxiv_id=None, version=None, title="x", abstract="", body=""),
        exclude_doc_id=doc.id,
        embedder=StubEmbedder(),
    )
    assert hit is None


@pytest.mark.parametrize(
    ("new", "old", "expected"),
    [("v2", "v1", "replace"), ("v1", "v7", "keep_existing")],
)
def test_version_comparison(new: str, old: str, expected: str) -> None:
    from app.dedup.service import _version_reason

    suggestion, reason = _version_reason(new, old)
    assert suggestion == expected
    assert old in reason


def test_ligatures_do_not_change_a_word() -> None:
    """A PDF may set "fi" as one glyph; the word is the same either way.

    Without this folding the vector copy of a paper and the OCR copy of the
    same paper disagree on every "conﬁguration"/"configuration".
    """
    assert fingerprint.tokenize("conﬁguration") == fingerprint.tokenize("configuration")
    assert fingerprint.tokenize("eﬃcient ﬂow") == ["efficient", "flow"]


class ScanCopyEmbedder(Embedder):
    """Stands in for an embedding model on the no-model path of L3."""

    def __init__(self) -> None:
        super().__init__(model_name="missing")
        self._load_error = "no weights"

    def _load(self) -> Any:  # pragma: no cover - never called
        raise RuntimeError("no weights")


async def test_a_scan_matches_its_vector_original(session: Any) -> None:
    """T2.4: after OCR, the scanned upload is recognised as the same content.

    Uses the two real fixtures — the vector PDF and a scan of the same paper —
    so the test measures the pipeline, not a hand-written approximation of it.
    The pair must be found without embeddings, because a scan is parsed before
    the model is warm (01 §8 allows the MinHash path on its own).
    """
    original, scanned = _fixture_candidates()
    await _add_doc(
        session,
        sha256="9" * 64,
        title=original.title,
        abstract=original.abstract,
        body=original.body,
    )
    hit = await check(session, scanned, embedder=ScanCopyEmbedder())
    assert hit is not None, "a scan of a paper already in the library must be found"
    assert hit.level == "content_duplicate"
    assert "格式" in hit.reason


async def test_an_unrelated_paper_is_not_matched_by_the_scan_rule(session: Any) -> None:
    """The control for the test above: a different paper stays unmatched."""
    _, scanned = _fixture_candidates()
    bert = _fixture_candidate("1810.04805_bert.pdf", "bert")
    await _add_doc(
        session,
        sha256="8" * 64,
        title=bert.title,
        abstract=bert.abstract,
        body=bert.body,
    )
    hit = await check(session, scanned, embedder=ScanCopyEmbedder())
    assert hit is None


def _fixture_candidate(name: str, doc_id: str) -> Candidate:
    """One fixture PDF as L3 sees it: title, abstract and opening body text."""
    from pathlib import Path

    from app.ingest.parser import parse_pdf

    path = Path(__file__).resolve().parent.parent / "fixtures" / "pdf" / name
    model = parse_pdf(path, doc_id).model
    return Candidate(
        sha256=doc_id,
        arxiv_id=None,
        version=None,
        title=model.meta.title,
        abstract=model.meta.abstract.text if model.meta.abstract else "",
        body="\n".join(b.text for b in model.blocks if b.type != "reference")[:8000],
    )


def _fixture_candidates() -> tuple[Candidate, Candidate]:
    """The vector original and the scan of it, as L3 sees them."""
    return _fixture_candidate("1706.03762v1.pdf", "vec"), _fixture_candidate("1706.03762v1_img.pdf", "scan")
