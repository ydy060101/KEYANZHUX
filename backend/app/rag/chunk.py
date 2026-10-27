"""Chunking for retrieval (01 §9, T3.1 groundwork used by T2.5).

A chunk is the unit the retriever matches and the answer cites, so it has two
jobs at once: small enough to be precise, large enough to be evidence. 01 §9
fixes the shape:

  * aggregate whole blocks — never split a sentence across two chunks;
  * 300–600 tokens, overlap at most 15%;
  * never cross a section boundary;
  * a table, a formula and a caption are each a chunk of their own;
  * keep `block_ids[]`, so every chunk maps back to anchors (H01).

The chunker runs window by window (T2.5), so it holds state across `feed`
calls: a paragraph may continue past a window boundary, and the next window's
first block then joins the open chunk instead of starting a new one.

T3.1 adds the embedding side: `stats` reports the distribution the card's
acceptance asks for, and the rules above are enforced rather than hoped for —
the guards below exist because the fixtures showed the first version breaking
them (folio numbers as chunks of their own, overlap tails re-emitted as
duplicates).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models.schemas import Block

# Tokens are estimated from characters rather than counted with bge-m3's
# tokenizer: chunking runs for every window of a 541-page book, and loading a
# tokenizer into the parse worker to size a buffer is not worth the memory.
# English prose averages ~4 characters per subword token, so `len / 4` is close
# enough against a 300–600 target, and it is deterministic (H06).
CHARS_PER_TOKEN = 4

# Blocks that stand alone: their content is not prose, and mixing one into a
# paragraph makes both the table and the paragraph unquotable.
STANDALONE = {"table", "figure", "formula", "caption"}
# Blocks with no retrievable content of their own.
SKIP = {"heading"}

# A block shorter than this with no letter in it at all is page furniture — a
# folio number, a stray "√" from a formula's radical, a lone list marker. On
# the fixtures these are 54 of 527 blocks in Transformer v1 and 76 of 1100 in
# GPT-3, and left in they become chunks of their own ("3"), which then compete
# with real paragraphs in retrieval. The length cap is what keeps a numeric
# table ("3 768 12 5.84 77.9 7") out of this rule: a table is a real block.
FURNITURE_CHARS = 40
_HAS_LETTER = re.compile(r"[^\W\d_]")


def is_furniture(text: str) -> bool:
    """Whether a block is a page number or a stray glyph rather than content."""
    stripped = text.strip()
    return len(stripped) < FURNITURE_CHARS and _HAS_LETTER.search(stripped) is None


def estimate_tokens(text: str) -> int:
    """Approximate subword tokens in `text`."""
    return max(1, round(len(text) / CHARS_PER_TOKEN))


@dataclass
class ChunkDraft:
    """A chunk before it has a document-wide id."""

    block_ids: list[str]
    section_id: str | None
    page_start: int
    page_end: int
    text: str


@dataclass
class Chunker:
    """Assembles chunks from blocks arriving window by window."""

    target: int = 450
    minimum: int = 300
    maximum: int = 600
    overlap_ratio: float = 0.15
    _buffer: list[Block] = field(default_factory=list)
    _tokens: int = 0
    _section: str | None = None
    _started: bool = False
    # The block ids the last emitted chunk covered, so an overlap tail that
    # closes on its own is recognised as an echo rather than a new chunk.
    _last_ids: set[str] = field(default_factory=set)
    # How many chunks came out below `minimum`. Not an error — a section can
    # genuinely be one short paragraph — but a number worth reporting, because
    # a sectioning bug shows up here first.
    short_chunks: int = 0
    # Blocks dropped as page furniture (a folio number, a stray glyph).
    skipped_furniture: int = 0

    def flush(self) -> list[ChunkDraft]:
        """Close the open chunk at the end of the document."""
        return self._close()

    # ---- internals -------------------------------------------------------

    @property
    def overlap_budget(self) -> int:
        return max(1, int(self.target * self.overlap_ratio))

    def feed(self, blocks: list[Block]) -> list[ChunkDraft]:
        """Add one window's blocks and return the chunks it completed.

        A chunk still open at the end of a window is *not* returned: the next
        window may continue it, and emitting it early would cut a paragraph in
        half. `flush` closes it when the document ends.
        """
        out: list[ChunkDraft] = []
        for block in blocks:
            if block.type in SKIP or not block.text.strip():
                continue
            if is_furniture(block.text):
                self.skipped_furniture += 1
                continue
            if self._started and block.section_id != self._section:
                out.extend(self._close())
            self._section = block.section_id
            self._started = True
            if block.type in STANDALONE:
                # A standalone block never joins a paragraph buffer, in either
                # direction, so the paragraph before it is closed first.
                out.extend(self._close())
                out.append(_single(block))
                continue
            tokens = estimate_tokens(block.text)
            if self._buffer and self._tokens + tokens > self.maximum:
                out.extend(self._close(keep_overlap=True))
            self._buffer.append(block)
            self._tokens += tokens
            if self._tokens >= self.target:
                out.extend(self._close(keep_overlap=True))
        return out

    def _close(self, *, keep_overlap: bool = False) -> list[ChunkDraft]:
        """Emit the buffered blocks, optionally carrying the tail forward.

        A buffer that ends below `minimum` is still a chunk: 01 §9 forbids a
        chunk that crosses a section boundary, and the only blocks it could be
        merged with are in the next section. It is reported, not silently
        merged, so a section that keeps producing stubs is visible.
        """
        if not self._buffer:
            return []
        blocks = self._buffer
        ids = [block.id for block in blocks]
        self._buffer = []
        self._tokens = 0
        # A buffer that is entirely the previous chunk's overlap tail is not a
        # chunk: it says nothing the previous one did not, and retrieval would
        # return the same text twice. This happens at a section boundary — the
        # tail was carried forward, then the next block turned out to be in a
        # new section, so the tail is all that is left to close. GPT-3's
        # fixtures produced two such echoes before this guard.
        if set(ids) <= self._last_ids:
            return []
        draft = ChunkDraft(
            block_ids=ids,
            section_id=blocks[0].section_id,
            page_start=blocks[0].page,
            page_end=blocks[-1].page,
            text="\n".join(block.text.strip() for block in blocks),
        )
        self._last_ids = set(ids)
        if len(blocks) == 1 and estimate_tokens(blocks[0].text) < self.minimum:
            self.short_chunks += 1
        if keep_overlap:
            self._carry_tail(blocks)
        return [draft]

    def _carry_tail(self, blocks: list[Block]) -> None:
        """Start the next chunk with the last block(s) of this one.

        Overlap exists so a fact that straddles a chunk boundary is still
        inside one chunk. It is capped by `overlap_ratio`, and it is never the
        whole buffer — a chunk that repeats its predecessor entirely would be
        retrieved twice for the same query.
        """
        budget = self.overlap_budget
        carried: list[Block] = []
        total = 0
        for block in reversed(blocks):
            tokens = estimate_tokens(block.text)
            if total + tokens > budget or len(carried) == len(blocks) - 1:
                break
            carried.insert(0, block)
            total += tokens
        self._buffer = carried
        self._tokens = total


def _single(block: Block) -> ChunkDraft:
    return ChunkDraft(
        block_ids=[block.id],
        section_id=block.section_id,
        page_start=block.page,
        page_end=block.page,
        text=block.text.strip(),
    )


@dataclass
class ChunkStats:
    """The length distribution T3.1's acceptance asks to see.

    Reported, not asserted in production: a section can genuinely be one short
    paragraph, and 01 §9's 300–600 is a target rather than a hard bound (a
    single block longer than 600 tokens cannot be split without cutting a
    sentence). The tests assert the parts that *are* hard — no chunk crosses a
    section, every chunk names its blocks, and the bulk of the text sits in
    target-sized chunks.
    """

    count: int = 0
    minimum: int = 0
    median: int = 0
    maximum: int = 0
    below_target: int = 0
    in_target: int = 0
    above_maximum: int = 0
    sections: int = 0
    skipped_furniture: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "count": self.count,
            "min_tokens": self.minimum,
            "median_tokens": self.median,
            "max_tokens": self.maximum,
            "below_target": self.below_target,
            "in_target": self.in_target,
            "above_maximum": self.above_maximum,
            "sections": self.sections,
            "skipped_furniture": self.skipped_furniture,
        }


def chunk_stats(
    drafts: list[ChunkDraft],
    *,
    minimum: int = 300,
    maximum: int = 600,
    skipped_furniture: int = 0,
    extra_tokens: list[int] | None = None,
    sections: int | None = None,
) -> ChunkStats:
    """Summarise a document's chunks for the parse result and the tests.

    `extra_tokens` carries the sizes of chunks the caller already dropped, so a
    windowed parse can report the whole book's distribution without holding
    every chunk's text (H11); `sections` then has to be supplied too, since the
    drafts that named them are gone.
    """
    tokens = sorted([estimate_tokens(draft.text) for draft in drafts] + (extra_tokens or []))
    if not tokens:
        return ChunkStats(skipped_furniture=skipped_furniture)
    return ChunkStats(
        count=len(tokens),
        minimum=tokens[0],
        median=tokens[len(tokens) // 2],
        maximum=tokens[-1],
        below_target=sum(1 for value in tokens if value < minimum),
        in_target=sum(1 for value in tokens if minimum <= value <= maximum),
        above_maximum=sum(1 for value in tokens if value > maximum),
        sections=sections if sections is not None else len({draft.section_id for draft in drafts}),
        skipped_furniture=skipped_furniture,
    )
