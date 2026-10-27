"""Reference markers ↔ bibliography entries (stage 8, T2.3).

A citation is a clickable span in the body text and an entry in the reference
list. The PDF usually knows the mapping already: LaTeX emits a GoTo link over
every marker whose destination is the entry's position, so `get_links` is the
primary source (01 §3). Only when a page carries no link annotations do we fall
back to reading the printed number.

Both paths end in the same place: a `Citation` with an anchor (block, page,
bbox), because a marker the reader cannot see and click is not evidence (H01).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from ..models.schemas import Block, Citation, Reference
from . import pdfio

logger = logging.getLogger(__name__)

CITE_RE = re.compile(r"\[(\d+(?:\s*[,\-–]\s*\d+)*)\]")
# A link rect holds one fragment of a marker: "[31,", "2,", "5]".
_MARKER_CHARS = re.compile(r"^[\[\]\d,\-–\s]+$")
# What may sit between two links of the same marker: nothing, a comma, a dash.
_SEPARATOR = re.compile(r"^[\s,\-–;]*$")
_MAX_GROUP_GAP = 8.0
_SAME_LINE = 4.0
# How far a destination may sit from an entry's top edge and still be that entry.
_TARGET_TOLERANCE = 20.0
# A marker with more entries than this is a range, not a list.
_MAX_RANGE = 50


@dataclass
class LinkGroup:
    """Adjacent link rects that together spell one marker."""

    page: int
    bbox: tuple[float, float, float, float]
    links: list[pdfio.Link] = field(default_factory=list)


@dataclass
class Coverage:
    """How much of the bibliography the body actually cites (T2.3)."""

    references: int = 0
    cited: int = 0
    uncited: int = 0
    dangling: int = 0
    unresolved_links: int = 0
    by_link: int = 0
    by_regex: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "references": self.references,
            "cited": self.cited,
            "uncited": self.uncited,
            "dangling": self.dangling,
            "unresolved_links": self.unresolved_links,
            "citations_by_link": self.by_link,
            "citations_by_regex": self.by_regex,
        }


def build_citations(
    doc: pdfio.Document,
    blocks: list[Block],
    references: list[Reference],
    *,
    page_limit: int | None = None,
) -> tuple[list[Citation], Coverage]:
    """Map every in-text marker to the reference entries it points at."""
    by_page = _references_by_page(blocks, references)
    reference_blocks = {reference.block_id for reference in references}
    citations: list[Citation] = []
    coverage = Coverage(references=len(references))
    linked_pages: set[int] = set()

    for page_no in range(1, min(page_limit or pdfio.page_count(doc), pdfio.page_count(doc)) + 1):
        page = pdfio.page(doc, page_no - 1)
        groups = _link_groups(page, page_no, by_page)
        if groups:
            linked_pages.add(page_no)
        for group, ref_ids in groups:
            if not ref_ids:
                coverage.unresolved_links += 1
                continue
            anchor = _anchor_for(blocks, page_no, group.bbox)
            if anchor is None or anchor.id in reference_blocks:
                coverage.unresolved_links += 1
                continue
            marker = _marker_text(page, group.bbox)
            citations.append(
                Citation(
                    id=f"c{len(citations) + 1}",
                    marker=marker,
                    ref_ids=_verify_against_text(ref_ids, marker),
                    block_id=anchor.id,
                    bbox=list(group.bbox),
                    method="link_annotation",
                )
            )

    citations.extend(_regex_citations(blocks, linked_pages, reference_blocks, len(citations)))
    coverage.by_link = sum(1 for item in citations if item.method == "link_annotation")
    coverage.by_regex = len(citations) - coverage.by_link
    _score(coverage, citations, references)
    return citations, coverage


def _marker_text(page: pdfio.Page, bbox: tuple[float, float, float, float]) -> str:
    """The visible marker, trimmed of the neighbouring text the clip catches.

    A clip rectangle catches whatever glyphs overlap it, so "[31," comes back
    as "pp [31," on a tightly set page. The marker is the bracketed run inside
    that text, not the whole of it.
    """
    raw = " ".join(pdfio.text_in_bbox(page, bbox).split())
    for opener, closer in (("[", "]"), ("(", ")")):
        start = raw.find(opener)
        if start < 0:
            continue
        end = raw.rfind(closer)
        return raw[start : end + 1] if end > start else raw[start:]
    return raw


def _verify_against_text(ref_ids: list[str], marker: str) -> list[str]:
    """Keep the printed numbers when the links disagree with them.

    The visible number is what the reader sees; a link that contradicts it is
    stale or misattached, so the text wins and the anchor is still recorded.
    """
    printed = [f"r{number}" for number in marker_numbers(marker)]
    if printed and set(printed) != set(ref_ids):
        logger.debug("link/text mismatch for %s: %s vs %s", marker, ref_ids, printed)
        return printed
    return ref_ids


def marker_numbers(marker: str) -> list[int]:
    """The entry numbers a printed marker names: '[31, 2, 5]' → [31, 2, 5]."""
    numbers: list[int] = []
    for match in CITE_RE.finditer(marker):
        numbers.extend(expand_marker(match.group(1)))
    return numbers


def expand_marker(spec: str) -> list[int]:
    """'3, 5-7' → [3, 5, 6, 7]."""
    numbers: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        span = re.match(r"^(\d+)\s*[-–]\s*(\d+)$", part)
        if span:
            low, high = int(span.group(1)), int(span.group(2))
            if 0 < high - low <= _MAX_RANGE:
                numbers.extend(range(low, high + 1))
        elif part.isdigit():
            numbers.append(int(part))
    return numbers


def _references_by_page(blocks: list[Block], references: list[Reference]) -> dict[int, list[Reference]]:
    """Reference entries grouped by the page they sit on, in reading order."""
    pages = {block.id: block.page for block in blocks}
    out: dict[int, list[Reference]] = {}
    for reference in references:
        page_no = pages.get(reference.block_id)
        if page_no is not None and reference.bbox:
            out.setdefault(page_no, []).append(reference)
    for entries in out.values():
        entries.sort(key=lambda ref: ref.bbox[1])
    return out


def _link_groups(
    page: pdfio.Page, page_no: int, by_page: dict[int, list[Reference]]
) -> list[tuple[LinkGroup, list[str]]]:
    """Merge link rects that together spell one marker.

    A marker such as "[31, 2, 5]" is three separate links, one per entry, and
    each rect holds only a fragment ("[31,", "2,", "5]"). Grouping restores the
    marker the reader sees.

    Two links are only merged when the text *between* them is itself part of a
    marker: a comma or a dash. Prose between them means they are separate
    markers ("[DCLT18], to 1.5 billion parameters [RWC+19]"), and merging those
    would produce one citation spanning a sentence. A link counts when it
    resolves to a bibliography entry or when its text looks like part of a
    numeric marker — the first covers author-year styles, which hold no number.
    """
    candidates: list[pdfio.Link] = []
    for link in pdfio.links(page):
        if link.page is None:
            continue
        text = pdfio.text_in_bbox(page, link.bbox)
        if not text:
            continue
        if _entry_at(link, by_page) is None and not _MARKER_CHARS.match(text):
            continue
        candidates.append(link)
    candidates.sort(key=lambda link: (round(link.bbox[1], 1), link.bbox[0]))

    out: list[tuple[LinkGroup, list[str]]] = []
    for link in candidates:
        if out and _joins(page, out[-1][0], link):
            group = out[-1][0]
            group.bbox = (
                min(group.bbox[0], link.bbox[0]),
                min(group.bbox[1], link.bbox[1]),
                max(group.bbox[2], link.bbox[2]),
                max(group.bbox[3], link.bbox[3]),
            )
            group.links.append(link)
            out[-1] = (group, _refs_from_links(group.links, by_page))
            continue
        group = LinkGroup(page=page_no, bbox=link.bbox, links=[link])
        out.append((group, _refs_from_links(group.links, by_page)))
    return out


def _joins(page: pdfio.Page, group: LinkGroup, link: pdfio.Link) -> bool:
    """Whether `link` continues the marker in `group` rather than starting one."""
    if abs(group.bbox[1] - link.bbox[1]) >= _SAME_LINE:
        return False
    gap = link.bbox[0] - group.bbox[2]
    if gap < -1:
        return False  # overlapping rects are one link's glyphs, not two markers
    if gap >= _MAX_GROUP_GAP:
        return False
    between = pdfio.text_in_bbox(page, (group.bbox[2], group.bbox[1], link.bbox[0], link.bbox[3]))
    return _SEPARATOR.match(between) is not None


def _refs_from_links(links: list[pdfio.Link], by_page: dict[int, list[Reference]]) -> list[str]:
    """Reference ids named by the links' destinations, in marker order."""
    ids: list[str] = []
    for link in links:
        reference = _entry_at(link, by_page)
        if reference is not None and reference.id not in ids:
            ids.append(reference.id)
    return ids


def _entry_at(link: pdfio.Link, by_page: dict[int, list[Reference]]) -> Reference | None:
    """The bibliography entry a link points at.

    The destination is a point on the entry's first line, so the nearest entry
    on that page whose top edge is within a line of it is the target.
    """
    if link.page is None or link.target is None:
        return None
    candidates = by_page.get(link.page, [])
    if not candidates:
        return None
    target_y = link.target[1]
    best = min(candidates, key=lambda ref: abs(ref.bbox[1] - target_y))
    if abs(best.bbox[1] - target_y) > _TARGET_TOLERANCE:
        return None
    return best


def _anchor_for(
    blocks: list[Block], page_no: int, bbox: tuple[float, float, float, float]
) -> Block | None:
    """The body block the marker sits in — its anchor (H01)."""
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    same_page = [block for block in blocks if block.page == page_no and len(block.bbox) == 4]
    for block in same_page:
        x0, y0, x1, y1 = block.bbox
        if x0 - 1 <= cx <= x1 + 1 and y0 - 1 <= cy <= y1 + 1:
            return block
    if not same_page:
        return None
    return min(same_page, key=lambda block: abs(block.bbox[1] - bbox[1]))


def _regex_citations(
    blocks: list[Block],
    linked_pages: set[int],
    reference_blocks: set[str],
    offset: int,
) -> list[Citation]:
    """Markers on pages that carry no link annotations, read from the text.

    The fallback is per page, not per block: a page that has link annotations
    already recorded its markers precisely, and scanning it again would count
    each one twice. Bibliography entries are skipped everywhere — the "[3]"
    that starts an entry is a label, not a citation.
    """
    out: list[Citation] = []
    for block in blocks:
        if block.type == "reference" or block.id in reference_blocks:
            continue
        if block.page in linked_pages:
            continue
        for match in CITE_RE.finditer(block.text):
            numbers = expand_marker(match.group(1))
            if not numbers:
                continue
            out.append(
                Citation(
                    id=f"c{offset + len(out) + 1}",
                    marker=match.group(0),
                    ref_ids=[f"r{number}" for number in numbers],
                    block_id=block.id,
                    bbox=list(block.bbox),
                    method="regex",
                )
            )
    return out


def _score(coverage: Coverage, citations: list[Citation], references: list[Reference]) -> None:
    """Count cited, uncited and dangling entries against the bibliography."""
    known = {reference.id for reference in references}
    used = {ref_id for citation in citations for ref_id in citation.ref_ids}
    coverage.cited = len(known & used)
    coverage.uncited = len(known - used)
    coverage.dangling = len(used - known)
