"""Typed access to PyMuPDF — the only module that calls its public API.

PyMuPDF ships `py.typed` but declares its methods as `(*args, **kwargs)`, so
strict mypy cannot check calls into it. Keeping every call here lets the rest
of the pipeline stay fully typed; the suppression below is scoped to this file.
"""

# mypy: disable-error-code="no-untyped-call, arg-type, var-annotated"

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pymupdf

# Re-exported so the pipeline annotates against one module.
Document = pymupdf.Document
Page = pymupdf.Page

RawBlock = tuple[float, float, float, float, str]


def open_document(path: Path) -> Document:
    return pymupdf.open(path)


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


def document_metadata(doc: Document) -> dict[str, Any]:
    return dict(doc.metadata or {})


def page_size(page: Page) -> tuple[float, float]:
    return float(page.rect.width), float(page.rect.height)
