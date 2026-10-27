"""OCR for scanned pages (stage 4, T2.4).

Only pages whose extractable text is below the threshold go through this; a
vector page keeps PyMuPDF's own text, which is exact and needs no guessing.
That is both the card's constraint and the honest choice: OCR is the fallback
for pages that have no text layer at all, not a replacement for one.

The engine is optional at runtime. If PaddleOCR cannot be imported or its
models are missing, the page yields no text and a warning is logged — a scanned
document then parses as "no text found" instead of crashing the worker (H08).

Every line keeps its bounding box in PDF points, so an OCR block anchors back
to the page exactly like a vector block does (H01).
"""

from __future__ import annotations

import logging
import re
import statistics
from dataclasses import dataclass
from typing import Any

import numpy as np

from . import pdfio

logger = logging.getLogger(__name__)

# Render scale for OCR. 1.5 is the cheapest that keeps 8pt body text readable,
# but it drops the section number of "6 Results" outright on the scanned
# Transformer; 2.0 reads it ("6 Results") and the whole printed contents come
# back, for about a second more per page. 2.5 and 3.0 read the same text with
# the number glued on ("6Results") and gain nothing further.
ZOOM = 2.0
# A line whose box is this much taller than wide is rotated text — a figure
# label, not body copy — and its OCR reading is not trustworthy.
_ROTATED_RATIO = 1.6
# A paragraph continues while the gap to the next line stays below this
# multiple of the page's line pitch; a bigger gap means a new block.
_PARAGRAPH_GAP = 0.6
_MAX_PITCH_SAMPLES = 400


@dataclass
class OcrLine:
    """One recognised text line, in PDF points (top-left origin)."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    score: float

    @property
    def height(self) -> float:
        return self.y1 - self.y0


_ENGINE: Any | None = None
_ENGINE_FAILED = False


def _engine() -> Any | None:
    """The PaddleOCR engine, created once per process.

    `torch` is imported before `paddle` on purpose: paddle's runtime load
    replaces the DLL search path and torch then fails to load `shm.dll` on
    Windows. Importing torch first fixes the order for the whole process.
    """
    global _ENGINE, _ENGINE_FAILED
    if _ENGINE is not None or _ENGINE_FAILED:
        return _ENGINE
    try:
        import torch  # noqa: F401
        from paddleocr import PaddleOCR  # type: ignore[import-untyped]

        _ENGINE = PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            text_detection_model_name="PP-OCRv5_mobile_det",
            text_recognition_model_name="PP-OCRv5_mobile_rec",
        )
    except Exception as exc:  # noqa: BLE001 - any import/init failure degrades
        _ENGINE_FAILED = True
        logger.warning("OCR engine unavailable, scanned pages will be empty: %s", exc)
        return None
    return _ENGINE


def available() -> bool:
    """Whether OCR can run in this process."""
    return _engine() is not None


def lines(page: pdfio.Page) -> list[OcrLine]:
    """Every horizontal text line on a page, with boxes in PDF points.

    Rotated lines are dropped here rather than downstream: they are figure
    labels set sideways, and a rotated word reads as noise ("uo!eo!dde" for
    "application"), which must never reach the document model (H02).
    """
    engine = _engine()
    if engine is None:
        return []
    width, height = pdfio.page_size(page)
    png = pdfio.crop_png(page, (0.0, 0.0, width, height), zoom=ZOOM)
    image = _decode(png)
    if image is None:
        return []
    try:
        result = engine.predict(image)[0]
    except Exception as exc:  # noqa: BLE001 - one bad page must not kill a job
        logger.warning("OCR failed on a page, leaving it empty: %s", exc)
        return []

    out: list[OcrLine] = []
    rows = zip(result["rec_texts"], result["rec_scores"], result["rec_polys"], strict=False)
    for text, score, poly in rows:
        line = _to_line(str(text), float(score), poly)
        if line is None:
            continue
        if line.height > (line.x1 - line.x0) * _ROTATED_RATIO:
            continue
        out.append(line)
    out.sort(key=lambda item: (round(item.y0, 1), item.x0))
    return out


def _decode(png: bytes) -> np.ndarray | None:
    try:
        import cv2

        return cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    except Exception as exc:  # noqa: BLE001 - OpenCV is part of the optional stack
        logger.warning("cannot decode a page for OCR: %s", exc)
        return None


def _to_line(text: str, score: float, poly: Any) -> OcrLine | None:
    """A polygon in render pixels becomes a box in PDF points."""
    try:
        points = [(float(point[0]) / ZOOM, float(point[1]) / ZOOM) for point in poly]
    except (TypeError, ValueError, IndexError):
        return None
    if not points:
        return None
    clean = " ".join(text.split())
    if not clean:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return OcrLine(clean, min(xs), min(ys), max(xs), max(ys), score)


def line_pitch(recognised: list[OcrLine]) -> float:
    """The page's typical distance between baselines.

    The median of consecutive gaps between line tops is robust to the wide
    spacing around headings, which is exactly what must not skew it.
    """
    tops = sorted({round(line.y0, 1) for line in recognised})
    gaps = [b - a for a, b in zip(tops, tops[1:], strict=False) if 2 < b - a < 60]
    if not gaps:
        return 10.0
    return statistics.median(gaps[:_MAX_PITCH_SAMPLES])


def page_blocks(page: pdfio.Page) -> list[pdfio.TypedBlock]:
    """OCR a page and assemble its lines into blocks.

    Lines are grouped into paragraphs by vertical spacing, which is the only
    layout signal a scan preserves: a line continues the paragraph above when
    the gap between them is under a fraction of the page's line pitch.
    """
    recognised = lines(page)
    if not recognised:
        return []
    pitch = line_pitch(recognised)
    groups = _group(recognised, pitch)
    body = _body_height(recognised)
    return [_to_block(group, body) for group in groups]


def _group(recognised: list[OcrLine], pitch: float) -> list[list[OcrLine]]:
    groups: list[list[OcrLine]] = []
    for line in recognised:
        previous = groups[-1][-1] if groups else None
        if previous is not None and _continues(previous, line, pitch, recognised):
            groups[-1].append(line)
        else:
            groups.append([line])
    return groups


# "12." / "[12] R. Smith" — the start of a bibliography entry.
_ENTRY_START = re.compile(r"^(?:\[\d{1,3}\]|\d{1,3}\.)\s*\S")


def _continues(previous: OcrLine, line: OcrLine, pitch: float, page_lines: list[OcrLine]) -> bool:
    """Whether `line` is the next line of the same paragraph."""
    if _ENTRY_START.match(line.text):
        return False  # a labelled entry always starts a block of its own
    if _is_standalone(previous, page_lines):
        return False  # a heading or a lone short line never absorbs its neighbour
    gap = line.y0 - previous.y1
    if gap > pitch * _PARAGRAPH_GAP:
        return False
    if gap < -pitch:
        return False  # side by side, not one under the other
    # A new column starts at a much smaller left edge than the running text.
    return line.x0 > previous.x0 - pitch * 2


def _is_standalone(line: OcrLine, page_lines: list[OcrLine]) -> bool:
    """Whether a line is set off from the text, like a heading or a label.

    A heading occupies a fraction of the measure and ends without punctuation;
    running text fills the column. Judging by the page's own text width rather
    than an absolute number keeps this working across page sizes.
    """
    if not page_lines:
        return False
    widest = max(item.x1 for item in page_lines) - min(item.x0 for item in page_lines)
    if widest <= 0:
        return False
    short = (line.x1 - line.x0) < widest * 0.5
    return short and not line.text.rstrip().endswith((".", ",", ";", ":"))


def _body_height(recognised: list[OcrLine]) -> float:
    heights = [line.height for line in recognised if line.height > 0]
    return statistics.median(heights) if heights else 10.0


def _to_block(group: list[OcrLine], body: float) -> pdfio.TypedBlock:
    first = group[0]
    # The same line-break rule as the vector path, so a scan and its vector
    # original produce the same words even though one came from OCR.
    text = pdfio.join_lines([line.text for line in group])
    size = max(line.height for line in group)
    return pdfio.TypedBlock(
        x0=min(line.x0 for line in group),
        y0=min(line.y0 for line in group),
        x1=max(line.x1 for line in group),
        y1=max(line.y1 for line in group),
        text=text,
        size=size,
        # A scan carries no font weight, so "bold" here means "set like a
        # heading": one short line, set off from the text above it by extra
        # leading. That is the typographic cue a reader uses as well.
        bold=_headed(first, group, body),
    )


# A section number and its title: "6 Results", "6Results", "3.2.1 Scaled".
# The space after a number is optional because the recogniser drops it; what
# may not follow is another digit, which would make "512" a heading. An
# appendix letter ("A Additional Details") does need its space, or every
# capitalised word in the document ("ByteNet", "Google Research") becomes a
# section.
_NUMBERED_TITLE = re.compile(r"^(?:\d+(?:\.\d+)*\s*\D|[A-Z]\.?\s+\D)")

_KEYWORDS = {
    "abstract",
    "introduction",
    "related",
    "background",
    "method",
    "methods",
    "approach",
    "experiments",
    "results",
    "discussion",
    "conclusion",
    "conclusions",
    "references",
    "acknowledgements",
    "acknowledgments",
    "appendix",
}


def _headed(first: OcrLine, group: list[OcrLine], body: float) -> bool:
    """Whether a block is set apart like a heading rather than running text.

    A scan carries no font weight, so the test is typographic and textual: one
    line, no closing punctuation, and either a section number with a title
    ("3.2 Attention") or a structural word ("Abstract"). Digits alone are a
    table cell or an axis label, never a heading — numeric blocks are what a
    naive rule turns into a table of contents ("512", "93.3", "9").

    The space after the number is optional: the recogniser reads "6 Results"
    as "6Results" about as often as it reads it correctly, and both are the
    same heading. What the number may not be is the whole line, and what may
    not follow it is another digit — "6.1" is a section, "512" is a value.
    """
    if len(group) != 1:
        return False
    text = first.text.strip()
    if not text or len(text) > 120 or "@" in text:
        return False
    if text.endswith((".", ",", ";", ":")):
        return False
    words = text.split()
    numbered = bool(_NUMBERED_TITLE.match(text)) and len(words) >= 2
    keyword = words[0].lower().strip(".:") in _KEYWORDS
    if not numbered and not keyword:
        return False
    return first.height >= body * 0.95 or numbered or keyword
