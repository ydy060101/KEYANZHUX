"""Typed access to PyMuPDF — the only module that calls its public API.

PyMuPDF ships `py.typed` but declares its methods as `(*args, **kwargs)`, so
strict mypy cannot check calls into it. Keeping every call here lets the rest
of the pipeline stay fully typed; the suppression below is scoped to this file.
"""

# mypy: disable-error-code="no-untyped-call, arg-type, var-annotated"

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf

# Re-exported so the pipeline annotates against one module.
Document = pymupdf.Document
Page = pymupdf.Page

RawBlock = tuple[float, float, float, float, str]


def open_document(path: Path) -> Document:
    return pymupdf.open(path)


def open_document_bytes(data: bytes) -> Document:
    return pymupdf.open(stream=data, filetype="pdf")


def close_document(doc: Document) -> None:
    doc.close()


def page_count(doc: Document) -> int:
    return int(doc.page_count)


def page(doc: Document, index: int) -> Page:
    return doc[index]


def iter_pages(doc: Document) -> Iterator[Page]:
    for index in range(page_count(doc)):
        yield doc[index]


def page_text(page: Page, mode: str = "text") -> str:
    return str(page.get_text(mode))


def page_blocks(page: Page) -> list[RawBlock]:
    """Text blocks as (x0, y0, x1, y1, text), skipping empty ones."""
    out: list[RawBlock] = []
    for block in page.get_text("blocks"):
        text = str(block[4])
        if text.strip():
            out.append((float(block[0]), float(block[1]), float(block[2]), float(block[3]), text))
    return out


def page_dict(page: Page) -> dict[str, Any]:
    """The raw `dict` extraction, used for font sizes."""
    return dict(page.get_text("dict"))


@dataclass
class TypedBlock:
    """A text block with the typography needed to recognise headings."""

    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    size: float
    bold: bool


_BOLD_MARKERS = ("bold", "black", "heavy", "semibold", "demibold", "medi")


def typed_blocks(page: Page) -> list[TypedBlock]:
    """Blocks with their dominant font size and whether the text is bold.

    Text and typography come from the same `dict` pass, so a block cannot be
    paired with the wrong font — which is what happens when `blocks` (which
    drops empty blocks) and `dict` (which keeps them) are indexed separately.
    """
    out: list[TypedBlock] = []
    for block in page_dict(page).get("blocks", []):
        texts: list[str] = []
        weights: dict[float, int] = {}
        bold_chars = 0
        total_chars = 0
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = str(span["text"])
                if not text.strip():
                    continue
                size = round(float(span["size"]), 1)
                texts.append(text)
                weights[size] = weights.get(size, 0) + len(text)
                total_chars += len(text)
                if any(marker in str(span.get("font", "")).lower() for marker in _BOLD_MARKERS):
                    bold_chars += len(text)
        joined = "".join(texts)
        if not joined.strip():
            continue
        size = max(weights, key=lambda s: weights[s]) if weights else 0.0
        out.append(
            TypedBlock(
                x0=float(block["bbox"][0]),
                y0=float(block["bbox"][1]),
                x1=float(block["bbox"][2]),
                y1=float(block["bbox"][3]),
                text=joined,
                size=size,
                bold=total_chars > 0 and bold_chars >= total_chars * 0.6,
            )
        )
    return out


def document_metadata(doc: Document) -> dict[str, Any]:
    return dict(doc.metadata or {})


def page_size(page: Page) -> tuple[float, float]:
    return float(page.rect.width), float(page.rect.height)


def crop_png(page: Page, bbox: tuple[float, float, float, float], *, zoom: float = 2.0) -> bytes:
    """Render one rectangle of a page as PNG bytes.

    Used for figures, tables and formulas: the crop is the ground truth when
    text extraction is unsure, so it is rendered at 2× for legibility.
    """
    clip = pymupdf.Rect(bbox[0], bbox[1], bbox[2], bbox[3])
    matrix = pymupdf.Matrix(zoom, zoom)
    pixmap = page.get_pixmap(matrix=matrix, clip=clip, alpha=False)
    return bytes(pixmap.tobytes("png"))


def image_boxes(page: Page) -> list[tuple[float, float, float, float]]:
    """Bounding boxes of the raster images placed on a page."""
    out: list[tuple[float, float, float, float]] = []
    for info in page.get_image_info():
        rect = info.get("bbox")
        if rect is None:
            continue
        x0, y0, x1, y1 = (float(v) for v in rect)
        if x1 - x0 > 8 and y1 - y0 > 8:
            out.append((x0, y0, x1, y1))
    return out


def drawing_boxes(page: Page) -> list[tuple[float, float, float, float]]:
    """Bounding boxes of vector drawings (diagrams drawn as paths)."""
    out: list[tuple[float, float, float, float]] = []
    for drawing in page.get_drawings():
        rect = drawing.get("rect")
        if rect is None:
            continue
        x0, y0, x1, y1 = float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)
        if x1 - x0 > 20 and y1 - y0 > 20:
            out.append((x0, y0, x1, y1))
    return out


@dataclass
class Bookmark:
    """One entry of the PDF's own outline, with the page it points at (1-based)."""

    level: int
    title: str
    page: int


def bookmarks(doc: Document) -> list[Bookmark]:
    """The embedded table of contents, or [] when the PDF has none.

    Titles are often just "1 Introduction" or "Introduction"; the caller
    normalises them. `page` is -1 in PyMuPDF when the target cannot be
    resolved, and those entries are dropped.
    """
    out: list[Bookmark] = []
    for level, title, page_no in doc.get_toc(simple=True):
        name = str(title).strip()
        if not name or int(page_no) < 1:
            continue
        out.append(Bookmark(level=max(1, int(level)), title=name, page=int(page_no)))
    return out
