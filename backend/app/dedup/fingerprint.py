"""MinHash fingerprints (01 §8 L3).

A shingle set per document, hashed with `n` permutations; the Jaccard estimate
is the fraction of positions where two signatures agree. Implemented directly
rather than pulling in datasketch so the parameters are visible and testable.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

import numpy as np

NUM_PERM = 64
SHINGLE_SIZE = 5
_MASK = (1 << 61) - 1
_WORD_RE = re.compile(r"[a-z0-9]+")

# A PDF may set "fi", "fl", "ff" as one glyph. The vector copy then reads
# "conﬁguration" where a scan of the same page reads "configuration", and a
# token comparison would count every such word as a difference between two
# copies of one paper. Folding them onto their letters is lossless.
_LIGATURES = str.maketrans(
    {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
     "ﬅ": "st", "ﬆ": "st"}
)

# Fixed coefficients so the same text always yields the same signature (H06).
_rng = np.random.default_rng(20240601)
_A = _rng.integers(1, _MASK, size=NUM_PERM, dtype=np.int64)
_B = _rng.integers(0, _MASK, size=NUM_PERM, dtype=np.int64)


def tokenize(text: str) -> list[str]:
    """Words, with typographic ligatures folded onto their letters.

    Lowercasing already drops case, which no duplicate rule should care about;
    a ligature is the same kind of notational difference.
    """
    return _WORD_RE.findall(text.translate(_LIGATURES).lower())


def shingles(tokens: list[str], size: int = SHINGLE_SIZE) -> list[int]:
    """Hashed word shingles; short texts fall back to the whole token set."""
    if len(tokens) < size:
        return [hash_token(" ".join(tokens))] if tokens else []
    return [hash_token(" ".join(tokens[i : i + size])) for i in range(len(tokens) - size + 1)]


def hash_token(token: str) -> int:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") & _MASK


def signature(text: str, *, permutations: int = NUM_PERM, size: int = SHINGLE_SIZE) -> list[int]:
    """MinHash signature of the text; empty text yields an empty list."""
    hashes = shingles(tokenize(text), size)
    if not hashes:
        return []
    values = np.asarray(hashes, dtype=np.int64)
    mins = (np.outer(_A[:permutations], values) + _B[:permutations, None]) % _MASK
    return [int(x) for x in mins.min(axis=1)]


def jaccard(sig_a: Iterable[int], sig_b: Iterable[int]) -> float:
    a = list(sig_a)
    b = list(sig_b)
    if not a or not b or len(a) != len(b):
        return 0.0
    matches = sum(1 for x, y in zip(a, b, strict=True) if x == y)
    return matches / len(a)


def fingerprint_text(blocks_text: Iterable[str], *, limit: int = 12) -> str:
    """The first blocks' text — what L3 compares, so a title page alone is not enough."""
    parts: list[str] = []
    for text in blocks_text:
        parts.append(text)
        if len(parts) >= limit:
            break
    return "\n".join(parts)
