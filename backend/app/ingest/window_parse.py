"""Windowed parsing of a long document (T2.5).

One pass over 541 pages holds every block, every crop's pixmap and the whole
bibliography in memory at once. Windowing changes that: pages are parsed a few
at a time, each window is persisted before the next is read, and the objects a
window built are dropped when it ends. That keeps peak memory flat (H11) and
makes progress reportable — a window is a unit of work that either finished or
did not.

A window also makes the document usable early: once its rows are committed the
pages it covers can be read, and once its chunks are committed they can be
retrieved, while the rest of the book is still parsing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..models.schemas import Asset, Block, OutlineItem
from . import pdfio
from .assets import extract_assets
from .parser import page_blocks, to_model_blocks
from .sections import SectionTracker
from .windows import Window

logger = logging.getLogger(__name__)


@dataclass
class WindowResult:
    """What one window produced, ready to persist."""

    window: Window
    blocks: list[Block]
    assets: list[Asset]
    outline: list[OutlineItem] = field(default_factory=list)


def parse_window(
    doc: pdfio.Document,
    window: Window,
    tracker: SectionTracker,
    doc_id: str,
    *,
    threshold: int,
    sizes: dict[str, float] | None = None,
) -> WindowResult:
    """Parse the pages of one window.

    `tracker` carries the sections and headings accumulated so far; it is
    mutated here so the next window continues where this one stopped.

    The bibliography is not read here: it is document-wide, starts at a
    heading and runs to the appendix across pages that need not sit in one
    window. `parse_task._parse_long` reads it once, from the stored rows, after
    the last window (T2.6).
    """
    blocks: list[Block] = []
    for page_no in window.page_numbers:
        page = pdfio.page(doc, page_no - 1)
        scanned = len(pdfio.page_text(page).strip()) < threshold
        raw = page_blocks(page, scanned=scanned)
        model_blocks = to_model_blocks(
            raw,
            page_no=page_no,
            scanned=scanned,
            start_order=len(blocks) + 1,
        )
        if sizes is not None:
            for block, source in zip(model_blocks, raw, strict=True):
                sizes[block.id] = source.size
        blocks.extend(model_blocks)

    tracker.assign(blocks, sizes)
    assets = extract_assets(doc, blocks, doc_id)

    return WindowResult(
        window=window,
        blocks=blocks,
        assets=assets,
        outline=tracker.outline(),
    )


