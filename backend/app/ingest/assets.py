"""Figures, tables and formulas (stage 7, T2.2).

Every asset keeps a crop of the page it came from. That crop is the fallback
the reader shows when the extracted structure is uncertain — a table whose
HTML is shaky, a formula whose LaTeX may be wrong — so a wrong guess never
becomes a wrong statement (H01, H04).

Tables and formulas are located by their caption or by their typography;
figures by the drawing and image regions above their caption.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from ..models.schemas import Asset, Block
from . import pdfio, storage

logger = logging.getLogger(__name__)

# A caption's label ends in a colon, or in a full stop followed by a space.
# Without that second condition the pattern also matches prose: "Table 2.1
# shows the sizes" parses as label "2" + separator "." + text "1 shows the
# sizes", which is how a real caption gets misread as a sentence and dropped.
_CAPTION = re.compile(
    r"^(figure|table|fig\.)\s*(\d+(?:\.\d+)*)\s*(?::|\.(?=\s))\s*(.*)$",
    re.IGNORECASE | re.DOTALL,
)
# A formula line: mostly symbols, digits and single letters, not prose.
_FORMULA_HINT = re.compile(r"[=∑∏∫√≈≤≥±×÷∂∇αβγδεθλμσϕω]")
_WORD = re.compile(r"[A-Za-z]{3,}")

# How far above a caption the graphic may start, as a fraction of page height.
_GRAPHIC_GAP = 0.35


@dataclass
class Caption:
    kind: str
    # As printed: "3" for Figure 3, "3.2" for Figure 3.2.
    label: str
    text: str
    page: int
    block: Block

    @property
    def number(self) -> int:
        return int(self.label.split(".")[0])


def _caption_of(block: Block) -> Caption | None:
    match = _CAPTION.match(" ".join(block.text.split()))
    if match is None:
        return None
    kind = "figure" if match.group(1).lower().startswith("fig") else "table"
    return Caption(
        kind=kind,
        label=match.group(2),
        text=match.group(3).strip(),
        page=block.page,
        block=block,
    )


def find_captions(blocks: list[Block]) -> list[Caption]:
    """Captions in reading order. A caption that is a sentence is not one.

    "Table 2 summarizes our results" reads like a caption but is body text, so
    a caption must not end like a sentence. Length is not the test: GPT-3 and
    BERT both set captions of 500-900 characters, and a length cap dropped
    them. What separates caption from prose is the label and its separator,
    which `_CAPTION` now requires.
    """
    found: list[Caption] = []
    for block in blocks:
        caption = _caption_of(block)
        if caption is None:
            continue
        # A caption that trails off mid-phrase was cut by a page break, and the
        # graphic it belongs to is on the next page.
        if caption.text.endswith(("and", "the", "of", "in", "with")):
            continue
        if caption.text[:1].islower() and caption.kind == "figure":
            continue
        found.append(caption)
    return found


def _graphic_region(
    page: pdfio.Page, caption: Block, blocks: list[Block] | None = None
) -> tuple[float, float, float, float] | None:
    """The graphic that belongs to a caption, or None.

    Placement is not fixed by kind: arXiv papers put table captions above the
    table as often as below, so both directions are tried and the nearer
    candidate wins. The search is bounded by a fraction of the page height so
    an unrelated diagram on the other column is not swept in.
    """
    _, height = pdfio.page_size(page)
    boxes = pdfio.image_boxes(page) + pdfio.drawing_boxes(page)
    if not boxes:
        return None
    if _is_full_page_image(boxes, page):
        # A scan is one image of the whole page, so there is no drawn region to
        # find. The graphic's extent is what the recogniser saw as labels above
        # or below the caption (see `_scan_region`).
        return _scan_region(caption, blocks or [], page)

    gap = height * _GRAPHIC_GAP
    above = [b for b in boxes if b[3] <= caption.bbox[1] + 8 and b[3] >= caption.bbox[1] - gap]
    below = [b for b in boxes if b[1] >= caption.bbox[3] - 8 and b[1] <= caption.bbox[3] + gap]
    candidates = above if len(above) >= len(below) else below
    if not candidates:
        return None
    x0 = min(b[0] for b in candidates)
    y0 = min(b[1] for b in candidates)
    x1 = max(b[2] for b in candidates)
    y1 = max(b[3] for b in candidates)
    return (x0, y0, x1, y1)


def _is_full_page_image(boxes: list[tuple[float, float, float, float]], page: pdfio.Page) -> bool:
    """True when the page is one scanned image rather than a placed figure."""
    width, height = pdfio.page_size(page)
    return any((b[2] - b[0]) >= width * 0.9 and (b[3] - b[1]) >= height * 0.9 for b in boxes)


_PROSE_WIDTH = 0.5
_MAX_SCAN_SPAN = 0.55


def _scan_region(caption: Block, blocks: list[Block], page: pdfio.Page) -> tuple[float, float, float, float] | None:
    """The graphic's box on a scanned page, found from the labels around it.

    A diagram on a scan carries its own text — node labels, axis ticks — which
    OCR reads as short lines. Those lines bound the graphic: the region runs
    from the nearest prose line above (or the page margin) to the caption, and
    covers the width the labels occupy. A table is the same idea with its
    caption above it.
    """
    width, height = pdfio.page_size(page)
    same_page = [block for block in blocks if block.page == caption.page and block.id != caption.id]
    above = [block for block in same_page if block.bbox[3] <= caption.bbox[1] + 4]
    below = [block for block in same_page if block.bbox[1] >= caption.bbox[3] - 4]
    side = above if len(above) >= len(below) else below
    if not side:
        return None

    def is_prose(block: Block) -> bool:
        return (block.bbox[2] - block.bbox[0]) > width * _PROSE_WIDTH

    labels: list[Block] = []
    for block in sorted(side, key=lambda b: -b.bbox[3] if side is above else b.bbox[1]):
        if is_prose(block):
            break  # running text: the graphic has ended
        labels.append(block)
        if len(labels) > 60:
            break
    if not labels:
        return None
    if side is above:
        top = min(block.bbox[1] for block in labels)
        bottom = caption.bbox[3]
    else:
        top = caption.bbox[1]
        bottom = max(block.bbox[3] for block in labels)
    if bottom - top > height * _MAX_SCAN_SPAN:
        return None  # the "labels" run most of the page: this is body text
    left = min([caption.bbox[0]] + [block.bbox[0] for block in labels])
    right = max([caption.bbox[2]] + [block.bbox[2] for block in labels])
    return (left, top, min(right, width), bottom)


def _union(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> tuple[float, float, float, float]:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def extract_assets(doc: pdfio.Document, blocks: list[Block], doc_id: str) -> list[Asset]:
    """Crop every figure, table and formula and record where they came from.

    Called once per window by the windowed parse (T2.5); every asset id it
    produces is page-scoped, so two windows can never collide.
    """
    out_dir = storage.asset_dir(doc_id)
    assets: list[Asset] = []
    captions = find_captions(blocks)
    table_regions: list[tuple[int, list[float]]] = []

    for caption in captions:
        page = pdfio.page(doc, caption.page - 1)
        region = _graphic_region(page, caption.block, blocks)
        caption_box = (
            caption.block.bbox[0],
            caption.block.bbox[1],
            caption.block.bbox[2],
            caption.block.bbox[3],
        )
        # With no drawing found the crop is the caption alone, so the reader
        # still has an anchor rather than nothing.
        region = caption_box if region is None else _union(region, caption_box)
        if caption.kind == "table":
            # A table's body is text, not a drawing, so it is not in the boxes
            # above; extend the crop over the rows directly under the caption.
            region = _table_body_region(blocks, caption, region)
            table_regions.append((caption.page, list(region)))
        assets.append(_write_asset(page, out_dir, doc_id, caption, region))

    assets.extend(_extract_formulas(doc, blocks, doc_id, out_dir, table_regions))
    logger.info("extracted %d assets for %s", len(assets), doc_id)
    return assets


def _table_body_region(
    blocks: list[Block],
    caption: Caption,
    region: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """Extend a table crop over the row blocks that follow its caption.

    Table rows extract as ordinary text blocks, so no drawing marks them. They
    are the consecutive blocks on the same page whose left edge lines up with
    the caption's and that sit below it, stopping at the first block that reads
    like prose (a sentence, which means the table has ended).
    """
    same_page = [block for block in blocks if block.page == caption.page and block.bbox[1] > caption.block.bbox[3] - 2]
    same_page.sort(key=lambda block: block.bbox[1])
    bottom = region[3]
    left = min(region[0], caption.block.bbox[0])
    right = max(region[2], caption.block.bbox[2])
    for block in same_page:
        if block.id == caption.block.id:
            continue
        text = block.text.strip()
        if len(text) > 300 or text.count(" ") > 40:
            break  # prose: the table has ended
        bottom = max(bottom, block.bbox[3])
        left = min(left, block.bbox[0])
        right = max(right, block.bbox[2])
        if bottom - region[1] > 400:
            break
    return (left, region[1], right, bottom)


def _write_asset(
    page: pdfio.Page,
    out_dir: Path,
    doc_id: str,
    caption: Caption,
    region: tuple[float, float, float, float],
) -> Asset:
    # The printed label keeps sub-figures apart: a paper with Figure 3 and
    # Figure 3.2 has two assets, not two claims on the id "f3".
    asset_id = f"{caption.kind[:1]}{caption.label}"
    path = out_dir / f"{asset_id}.png"
    path.write_bytes(pdfio.crop_png(page, region))
    return Asset(
        id=asset_id,
        kind="figure" if caption.kind == "figure" else "table",
        page=caption.page,
        bbox=list(region),
        path=str(path),
    )


def _looks_like_formula(block: Block, table_regions: list[tuple[int, list[float]]]) -> bool:
    """Symbol-dense, prose-poor, and short — the shape of a displayed formula."""
    text = block.text.strip()
    if not text or len(text) > 160:
        return False
    if _inside_table(block, table_regions):
        return False  # a table header or cell, not a formula
    words = _WORD.findall(text)
    if len(words) > 4:
        return False
    symbols = len(_FORMULA_HINT.findall(text))
    return symbols >= 2 or (symbols >= 1 and len(text) < 80)


def _inside_table(block: Block, table_regions: list[tuple[int, list[float]]]) -> bool:
    for page, bbox in table_regions:
        if block.page != page:
            continue
        if (
            block.bbox[0] >= bbox[0] - 4
            and block.bbox[2] <= bbox[2] + 4
            and block.bbox[1] >= bbox[1] - 4
            and block.bbox[3] <= bbox[3] + 4
        ):
            return True
    return False


def _extract_formulas(
    doc: pdfio.Document,
    blocks: list[Block],
    doc_id: str,
    out_dir: Path,
    table_regions: list[tuple[int, list[float]]] | None = None,
) -> list[Asset]:
    """Crop formula-like blocks. The LaTeX comes later (T7); the crop is now.

    Formula ids are page-scoped (`eq12_3`), like block ids: a windowed parse
    (T2.5) calls this once per window, and a running counter would restart at
    `eq1` in the second window — the same id naming two different formulas,
    and a re-parsed window colliding with its own earlier rows.
    """
    assets: list[Asset] = []
    seen: set[tuple[int, str]] = set()
    tables = table_regions or []
    per_page: dict[int, int] = {}
    for block in blocks:
        if not _looks_like_formula(block, tables):
            continue
        key = (block.page, block.id)
        if key in seen:
            continue
        seen.add(key)
        per_page[block.page] = per_page.get(block.page, 0) + 1
        asset_id = f"eq{block.page}_{per_page[block.page]}"
        page = pdfio.page(doc, block.page - 1)
        bbox = (block.bbox[0], block.bbox[1], block.bbox[2], block.bbox[3])
        path = out_dir / f"{asset_id}.png"
        path.write_bytes(pdfio.crop_png(page, bbox))
        assets.append(Asset(id=asset_id, kind="formula", page=block.page, bbox=list(bbox), path=str(path)))
    return assets
