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
"""

from __future__ import annotations

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
    # How many chunks came out below `minimum`. Not an error — a section can
    # genuinely be one short paragraph — but a number worth reporting, because
    # a sectioning bug shows up here first.
    short_chunks: int = 0

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
        draft = ChunkDraft(
            block_ids=[block.id for block in blocks],
            section_id=blocks[0].section_id,
            page_start=blocks[0].page,
            page_end=blocks[-1].page,
            text="\n".join(block.text.strip() for block in blocks),
        )
        self._buffer = []
        self._tokens = 0
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
