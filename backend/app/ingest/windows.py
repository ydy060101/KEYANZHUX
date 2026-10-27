"""Page windows for long documents (T2.5).

A 541-page book parsed in one pass holds every page's extraction and every
crop's pixmap at once. Parsing it in windows of 20 pages means only one
window's intermediate objects are alive at a time (H11), and it gives the job
something to report progress on: a window is a unit of work that either
finished or did not.

The plan is a pure function of the page count and the window size, so a
resumed run produces exactly the windows the interrupted run had.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Window:
    """A run of pages, numbered from 1 like every page in the document model."""

    index: int
    start: int
    end: int

    @property
    def pages(self) -> range:
        """0-based page indices, which is what PyMuPDF takes."""
        return range(self.start - 1, self.end)

    @property
    def page_numbers(self) -> range:
        """1-based page numbers, which is what the document model stores."""
        return range(self.start, self.end + 1)

    @property
    def size(self) -> int:
        return self.end - self.start + 1

    @property
    def label(self) -> str:
        return f"p{self.start}-{self.end}"


def plan(page_count: int, size: int) -> list[Window]:
    """Every window covering `page_count` pages.

    A window size below 1 would produce an infinite plan and a page count of 0
    an empty one; both are clamped rather than raising, because a malformed PDF
    must degrade to "nothing to parse", not to a crashed worker (H08).
    """
    if page_count <= 0:
        return []
    step = max(1, size)
    windows: list[Window] = []
    start = 1
    while start <= page_count:
        end = min(start + step - 1, page_count)
        windows.append(Window(index=len(windows) + 1, start=start, end=end))
        start = end + 1
    return windows


def is_long(page_count: int, size: int) -> bool:
    """Whether the document needs windowing at all.

    A 15-page paper is cheaper to parse in one pass — no per-window
    transaction, no cross-window chunker state — so the test is "more than one
    window", not "a large book".
    """
    return page_count > max(1, size)
