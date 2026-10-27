"""Reading order for a page's text blocks (stage 3).

Single-column pages read top to bottom. Two-column pages read the left column,
then the right — but a full-width block (a title, a wide figure, a centred
equation) splits the page into horizontal bands, and each band is read
column-major. Without the bands, body text below a full-width block would be
emitted after headings that visually precede it.

The same rules serve the vector path (boxes from PyMuPDF) and the OCR path
(boxes from PaddleOCR), which is why this module works on bare boxes.
"""

from __future__ import annotations

from . import pdfio

NARROW = 0.6
# A body line fills most of its column, so it is at least this fraction of the
# page wide. Author names, figure labels and table cells are far narrower.
_BODY_LINE = 0.35
_MIN_BODY_LINES = 3


def looks_two_column(blocks: list[pdfio.TypedBlock], width: float) -> bool:
    """True when the page's body text sits in two narrow columns.

    Counting blocks is not enough: a title page lists the authors side by side,
    and those short name blocks look exactly like two columns. What a column
    really has is *lines of text* — blocks that span most of a column's width —
    so each side must contain several of them. Weighing the text by width then
    separates two columns from a page that merely has fragments to the right.
    """
    if width <= 0:
        return False
    wide_chars = narrow_chars = 0
    left_lines = right_lines = 0
    for block in blocks:
        length = len(block.text.strip())
        block_width = block.x1 - block.x0
        if block_width > width * NARROW:
            wide_chars += length
            continue
        narrow_chars += length
        if block_width < width * _BODY_LINE:
            continue  # a label or a name, not a body line
        if (block.x0 + block.x1) / 2 < width / 2:
            left_lines += 1
        else:
            right_lines += 1
    total = wide_chars + narrow_chars
    if total == 0:
        return False
    return left_lines >= _MIN_BODY_LINES and right_lines >= _MIN_BODY_LINES and narrow_chars > wide_chars


def order(blocks: list[pdfio.TypedBlock], width: float) -> list[pdfio.TypedBlock]:
    """Blocks in the order a reader moves through the page."""
    by_position = sorted(blocks, key=lambda b: (round(b.y0, 1), b.x0))
    if not looks_two_column(blocks, width):
        return by_position

    def column_major(band: list[pdfio.TypedBlock]) -> list[pdfio.TypedBlock]:
        left = [b for b in band if (b.x0 + b.x1) / 2 < width / 2]
        right = [b for b in band if (b.x0 + b.x1) / 2 >= width / 2]
        return sorted(left, key=lambda b: (round(b.y0, 1), b.x0)) + sorted(right, key=lambda b: (round(b.y0, 1), b.x0))

    ordered: list[pdfio.TypedBlock] = []
    band: list[pdfio.TypedBlock] = []
    for block in by_position:
        if block.x1 - block.x0 > width * NARROW:
            ordered.extend(column_major(band))
            band = []
            ordered.append(block)
        else:
            band.append(block)
    ordered.extend(column_major(band))
    return ordered
