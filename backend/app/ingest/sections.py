"""Section assignment for a document read one window at a time (T2.5).

A block's `section_id` says which heading it belongs to. In a single pass the
whole block list is at hand, so `outline.build_outline` can match headings to
blocks and then walk the list once. A windowed parse never has the whole list:
it must decide a window's sections from the headings seen so far plus the ones
inside the window.

The rule is the same either way — a block belongs to the most recent heading at
or before it — so this tracker reproduces `_fill_section_ids` without holding
the document. Three things make that correct across window boundaries:

  * heading ids are assigned from the bookmark list up front (`h1`, `h2`, …),
    so the id a window writes is the id the final outline reports;
  * a heading is placed by matching its page and title against this window's
    blocks, so a title that wrapped or lost its number still lands;
  * `_current` carries over from the previous window, so text before a
    window's first heading keeps the section it was already in.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..models.schemas import Block, OutlineItem
from . import pdfio
from .outline import Heading, from_blocks, merged_bookmarks, normalise_title, title_stem

logger = logging.getLogger(__name__)


@dataclass
class Placed:
    """A heading matched to the block that renders it."""

    id: str
    title: str
    level: int
    page: int
    top: float
    block_id: str


@dataclass
class SectionTracker:
    """Assigns section ids to blocks as windows arrive.

    `bookmarks` is empty for a PDF with no outline, in which case headings are
    recognised window by window with the same font-size and numbering rules
    the single pass uses.
    """

    bookmarks: list[Heading] = field(default_factory=list)
    placed: list[Placed] = field(default_factory=list)
    _next_id: int = 0
    _current: Placed | None = None
    _by_block: dict[str, Placed] = field(default_factory=dict)

    @classmethod
    def for_document(cls, doc: pdfio.Document) -> SectionTracker:
        bookmarks = merged_bookmarks(doc)
        for index, heading in enumerate(bookmarks):
            heading.id = f"h{index + 1}"
        return cls(bookmarks=bookmarks, _next_id=len(bookmarks))

    @property
    def uses_bookmarks(self) -> bool:
        return bool(self.bookmarks)

    def assign(self, blocks: list[Block], sizes: dict[str, float] | None = None) -> None:
        """Give every block in `blocks` its section, placing its headings.

        `blocks` is one window in reading order. Headings from earlier windows
        are already placed, so walking the list and switching section at each
        heading block is enough — the window boundary is not special. `sizes`
        carries each block's font size for the no-bookmark path, where level is
        inferred from typography.
        """
        if not blocks:
            return
        if self.uses_bookmarks:
            self._place_bookmarks(blocks)
        else:
            self._place_detected(blocks, sizes or {})
        for block in blocks:
            placed = self._by_block.get(block.id)
            if placed is not None:
                self._current = placed
                block.type = "heading"
            if self._current is not None:
                block.section_id = self._current.id

    def outline(self) -> list[OutlineItem]:
        """The heading tree as accumulated, in reading order."""
        return [
            OutlineItem(
                id=item.id,
                level=item.level,
                title=item.title[:200],
                page=item.page,
                block_id=item.block_id,
            )
            for item in self.placed
        ]

    # ---- bookmark path ---------------------------------------------------

    def _place_bookmarks(self, blocks: list[Block]) -> None:
        """Match this window's bookmark headings to the blocks rendering them."""
        first, last = blocks[0].page, blocks[-1].page
        for heading in self.bookmarks:
            if heading.block_id or not first <= heading.page <= last:
                continue
            block = _match(heading, blocks, set(self._by_block))
            if block is None:
                continue
            heading.block_id = block.id
            self._add(heading, block)

    # ---- rules path ------------------------------------------------------

    def _place_detected(self, blocks: list[Block], sizes: dict[str, float]) -> None:
        """Recognise headings inside the window, continuing the numbering.

        A long book usually ships an outline, so this path is for the rare one
        that does not. Levels come from the window's own font sizes, which is
        the same evidence the single pass uses over the whole document.
        """
        candidates = [block for block in blocks if block.id not in self._by_block]
        window_sizes = {block.id: sizes.get(block.id, _block_height(block)) for block in candidates}
        body = _median(list(window_sizes.values()))
        for heading in from_blocks(candidates, body_size=body, sizes=window_sizes):
            block = next((b for b in blocks if b.id == heading.block_id), None)
            if block is None or block.id in self._by_block:
                continue
            self._next_id += 1
            heading.id = f"h{self._next_id}"
            self._add(heading, block)

    # ---- shared ----------------------------------------------------------

    def _add(self, heading: Heading, block: Block) -> None:
        placed = Placed(
            id=heading.id,
            title=heading.title,
            level=heading.level,
            page=heading.page,
            top=float(block.bbox[1]) if len(block.bbox) == 4 else 0.0,
            block_id=block.id,
        )
        self.placed.append(placed)
        self.placed.sort(key=lambda item: (item.page, item.top))
        self._by_block[block.id] = placed


def _match(heading: Heading, blocks: list[Block], used: set[str]) -> Block | None:
    """The block on the heading's page that renders its title.

    Bookmarks differ from the rendered text in two ways this handles: case,
    and numbering. The book's outline says "Unsupervised learning" while the
    page prints "1.2 Unsupervised learning", so comparing the titles with the
    number stripped is what lets the bookmark land on its heading — without it
    the tree of a real book comes back almost empty.
    """
    target = normalise_title(heading.title)
    stem = title_stem(heading.title)
    same_page = [block for block in blocks if block.page == heading.page and block.id not in used]
    for block in same_page:
        if normalise_title(block.text) == target:
            return block
    for block in same_page:
        text = normalise_title(block.text)
        if text.lower() == target.lower() or title_stem(block.text) == stem:
            return block
    return None


def _block_height(block: Block) -> float:
    return block.bbox[3] - block.bbox[1] if len(block.bbox) == 4 else 0.0


def _median(values: list[float]) -> float:
    if not values:
        return 10.0
    ordered = sorted(values)
    return ordered[len(ordered) // 2]
