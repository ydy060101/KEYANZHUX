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

_CAPTION = re.compile(
    r"^(figure|table|fig\.)\s*(\d+(?:\.\d+)?)\s*[:.]\s*(.*)$", re.IGNORECASE | re.DOTALL
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
    a caption must not end like a sentence and must stay short.
    """
    found: list[Caption] = []
    for block in blocks:
        caption = _caption_of(block)
        if caption is None:
            continue
        if len(caption.text) > 400 or caption.text.endswith(("and", "the", "of")):
            continue
        if caption.text[:1].islower() and caption.kind == "figure":
            continue
        found.append(caption)
    return found


def _graphic_region(
    page: pdfio.Page, caption: Block
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


def _union(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> tuple[float, float, float, float]:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def extract_assets(doc: pdfio.Document, blocks: list[Block], doc_id: str) -> list[Asset]:
    """Crop every figure, table and formula and record where it came from."""
    out_dir = storage.asset_dir(doc_id)
    assets: list[Asset] = []
    captions = find_captions(blocks)
    table_regions: list[tuple[int, list[float]]] = []

    for caption in captions:
        page = pdfio.page(doc, caption.page - 1)
        region = _graphic_region(page, caption.block)
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
    same_page = [
        block
        for block in blocks
        if block.page == caption.page and block.bbox[1] > caption.block.bbox[3] - 2
    ]
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
    """Crop formula-like blocks. The LaTeX comes later (T7); the crop is now."""
    assets: list[Asset] = []
    seen: set[tuple[int, str]] = set()
    tables = table_regions or []
    counter = 0
    for block in blocks:
        if not _looks_like_formula(block, tables):
            continue
        key = (block.page, block.id)
        if key in seen:
            continue
        seen.add(key)
        counter += 1
        asset_id = f"eq{counter}"
        page = pdfio.page(doc, block.page - 1)
        bbox = (block.bbox[0], block.bbox[1], block.bbox[2], block.bbox[3])
        path = out_dir / f"{asset_id}.png"
        path.write_bytes(pdfio.crop_png(page, bbox))
        assets.append(Asset(id=asset_id, kind="formula", page=block.page, bbox=list(bbox), path=str(path)))
    return assets
