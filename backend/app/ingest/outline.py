"""Heading tree (stage 6, T2.1).

The PDF's own outline is authoritative when it exists: it is what the authors
(or the publisher) declared the structure to be, so it beats any guess made
from font sizes. Only when a PDF has no usable outline do we fall back to
font-size and numbering rules.

Levels are capped at 3 because the reader's left rail only shows three; deeper
entries are folded into their nearest ancestor rather than dropped, so no
heading disappears from the tree.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from ..models.schemas import Block, OutlineItem
from . import pdfio

logger = logging.getLogger(__name__)

MAX_LEVEL = 3

# "1 Introduction", "3.2.1 Multi-Head Attention", "1Introduction" — some
# publishers set no space after the number, so the separator is optional but
# the title must still start with a non-digit.
_NUMBERED = re.compile(r"^(\d+(?:\.\d+){0,3})\.?\s*(\D.*)$")
# "AAdditional Details", "B Detailed Setup" — appendices letter their sections.
_LETTERED = re.compile(r"^([A-Z])(?=[A-Z][a-z])(.*)$")
# "Abstract", "References", "Appendix A" — unnumbered but structural.
_UNNUMBERED = re.compile(
    r"^(abstract|introduction|related work|background|method|methods|approach|"
    r"experiments?|results?|discussion|conclusion|conclusions|references|"
    r"acknowledge?ments?|appendix(\s+[a-z])?)\b",
    re.IGNORECASE,
)
_WHITESPACE = re.compile(r"\s+")


@dataclass
class Heading:
    """A candidate heading before it becomes an OutlineItem."""

    title: str
    page: int
    level: int
    block_id: str = ""
    id: str = ""


def normalise_title(text: str) -> str:
    """Collapse whitespace and restore the space some PDFs drop after a number.

    BERT's PDF extracts "1Introduction" and "3.2Fine-tuning BERT" because the
    number and title are separate spans with no space between them; the tree
    should read like the printed page, not like the raw extraction.
    """
    collapsed = _WHITESPACE.sub(" ", text).strip()
    match = _NUMBERED.match(collapsed)
    if match is not None:
        return f"{match.group(1)} {match.group(2)}".strip()
    lettered = _LETTERED.match(collapsed)
    if lettered is not None:
        return f"{lettered.group(1)} {lettered.group(2)}".strip()
    return collapsed


def _merge_wrapped(headings: list[Heading]) -> list[Heading]:
    """Join a title that wrapped onto a second line into one entry.

    A wrapped title arrives as two blocks: the first does not end a sentence
    and the second starts in lower case or continues the quote. They must be
    merged or the tree shows half a title, as with BERT's appendix.
    """
    merged: list[Heading] = []
    for heading in headings:
        previous = merged[-1] if merged else None
        # A wrapped line is a continuation when the previous one does not end
        # a sentence and this one starts in lower case — or when the previous
        # ends mid-phrase ("for", "of"), which is how titles break.
        continues = heading.title[:1].islower() or previous is not None and _ends_open(previous.title)
        if (
            previous is not None
            and continues
            and previous.page == heading.page
            # Level is ignored: a wrapped line can be classified one level off
            # because its font size or leading differs slightly.
            and not previous.title.endswith((".", "?", "!"))
            and len(previous.title) + len(heading.title) <= 200
        ):
            previous.title = f"{previous.title} {heading.title}".strip()
            continue
        merged.append(heading)
    return merged


def _ends_open(title: str) -> bool:
    """True when a title ends on a word that cannot finish a phrase."""
    return title.split()[-1].lower() in {"of", "for", "and", "the", "in", "on", "to", "with"}


def _number_depth(title: str) -> int | None:
    match = _NUMBERED.match(normalise_title(title))
    if match is None:
        return None
    return match.group(1).count(".") + 1


def _number_prefix(title: str) -> tuple[int, ...] | None:
    match = _NUMBERED.match(normalise_title(title))
    if match is None:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def _follows_sequence(previous: tuple[int, ...] | None, current: tuple[int, ...]) -> bool:
    """A numbered heading must continue the document's numbering.

    Figure labels and equation fragments look exactly like headings by
    typography ("1Introduction", "C", "T1"); what they cannot do is appear in
    the right numeric order. Accepting only numbers that advance from the
    previous heading is what separates the two.
    """
    if previous is None:
        return current[0] == 1
    if len(current) > len(previous):
        # Deeper than the previous heading: a subsection starts at 1 under it.
        return current[-1] == 1 and current[:-1] == previous[: len(current) - 1]
    if len(current) == len(previous):
        # Same depth: it must be the next sibling, never a restart. This is
        # what rejects a figure label reading "1Introduction" mid-paper.
        return current[:-1] == previous[:-1] and current[-1] == previous[-1] + 1
    # Shallower: it must be an ancestor's next sibling.
    return current[:-1] == previous[: len(current) - 1] and current[-1] in {
        previous[len(current) - 1] + 1,
        1,
    }


def _cap_level(level: int) -> int:
    return max(1, min(MAX_LEVEL, level))


def from_bookmarks(doc: pdfio.Document) -> list[Heading]:
    """The embedded outline, with levels clamped to MAX_LEVEL.

    A bookmark whose level jumps (1 → 4) is clamped to 3 rather than being
    pushed under a heading that does not exist; nesting is repaired by the
    caller when it assigns section ids.
    """
    marks = pdfio.bookmarks(doc)
    return [
        Heading(title=normalise_title(mark.title), page=mark.page, level=_cap_level(mark.level))
        for mark in marks
        if normalise_title(mark.title)
    ]


def merged_bookmarks(doc: pdfio.Document) -> list[Heading]:
    """The bookmark headings, wrapped titles already joined.

    Public because the windowed parse needs the same headings, with the same
    ids, before it has any blocks: a section boundary decides which section a
    window's text belongs to, and it must not depend on having seen the whole
    document (T2.5).
    """
    return _merge_wrapped(from_bookmarks(doc))


def title_stem(text: str) -> str:
    """A heading's title without its section number, lowercased.

    Bookmarks and the printed page disagree about numbering: the book's
    outline says "Unsupervised learning" and the page says "1.2 Unsupervised
    learning". Comparing the stems is what lets one find the other.
    """
    match = _NUMBERED.match(normalise_title(text))
    return (match.group(2) if match else text).strip().lower()


def _size_of(block: Block, sizes: dict[str, float]) -> float:
    return sizes.get(block.id, 0.0)


_BOLD_FLAGS = ("bold", "black", "heavy", "semibold", "demibold")

# Displayed maths: letters glued to digits, or operators with no spacing.
_FORMULA_HINT = re.compile(r"[=∑∏∫√≈≤≥±×÷∂∇^_]")
# A digit written against a letter — "2i", "100002i" — is how maths sets a
# subscript, and how no heading ever reads a section number ("3.2.2").
_GLUED_DIGIT = re.compile(r"[A-Za-z]\d|\d[A-Za-z]")


def _is_formula_like(text: str) -> bool:
    """True for a line that reads as an equation rather than as words.

    "PE(pos,2i+1) = cos(pos/100002i/dmodel)" was the largest block on its page
    and so entered the heading tree; a heading is words, and a formula is not.
    The leading section number is removed first, because "3.2.2 Multi-Head" and
    BERT's "1Introduction" are glued digits that belong to a heading.
    """
    body = _NUMBERED.sub(r"\2", text)
    if _GLUED_DIGIT.search(body) or _FORMULA_HINT.search(body):
        return True
    letters = sum(1 for char in body if char.isalpha())
    solid = sum(1 for char in body if not char.isspace())
    return solid > 0 and letters / solid < 0.6


def _looks_like_heading(block: Block, body_size: float, sizes: dict[str, float]) -> bool:
    """Short, single-line, bold, and either numbered or larger than body text."""
    text = normalise_title(block.text)
    if not text or len(text) > 120 or "\n" in block.text.strip():
        return False
    # An address is never a heading, however it is typeset — and an OCR'd
    # email reads "1 lion@google.com", which otherwise looks numbered.
    if "@" in text or "://" in text:
        return False
    # A formula is not a heading even when it is the largest thing on the page:
    # displayed maths is dense in digits and operators, prose is not.
    if _is_formula_like(text):
        return False
    if text.endswith((".", ",", ";")) and _number_depth(text) is None:
        return False
    if _UNNUMBERED.match(text):
        return True
    numbered = _number_depth(text) is not None
    # Strictly larger, not merely different: figure labels are set a point or
    # two *smaller* than body text, and a tolerance of 0.6 admitted them.
    larger = _size_of(block, sizes) > body_size + 0.4
    body_height = body_size if body_size > 0 else 1.0
    if numbered:
        return block.bold or larger or _taller(block, sizes, body_height)
    return block.bold and (larger or _taller(block, sizes, body_height))


def _taller(block: Block, sizes: dict[str, float], body_height: float) -> bool:
    """Whether a block's own box is clearly taller than the body's line box.

    The OCR path has no font sizes, only block heights, so a heading there is
    recognised by being set larger than running text — the same test as `larger`
    on the vector path, expressed in the units that path does have.
    """
    return body_height > 0 and _size_of(block, sizes) > body_height * 1.05


def from_blocks(blocks: list[Block], body_size: float, sizes: dict[str, float]) -> list[Heading]:
    """Font-size and numbering rules, for PDFs without an outline.

    A heading must look like one on every axis: short, one line, bold, and
    either numbered ("3.2 Method") or visibly larger than body text. Requiring
    all of them is what keeps figure labels, footnotes and running text out of
    the tree — BERT's PDF has no outline, and size alone matched 126 blocks.
    """
    candidates = [block for block in blocks if _looks_like_heading(block, body_size, sizes)]
    # Numbered candidates must advance in sequence; a figure label that reads
    # "1Introduction" fails here because the numbering jumps.
    kept: list[Block] = []
    previous: tuple[int, ...] | None = None
    for block in candidates:
        prefix = _number_prefix(block.text)
        if prefix is not None:
            if not _follows_sequence(previous, prefix):
                continue
            previous = prefix
        kept.append(block)

    distinct = sorted({round(_size_of(block, sizes), 1) for block in kept}, reverse=True)
    headings: list[Heading] = []
    for block in kept:
        depth = _number_depth(block.text)
        if depth is not None:
            level = _cap_level(depth)
        elif _UNNUMBERED.match(normalise_title(block.text)):
            level = 1
        else:
            size = round(_size_of(block, sizes), 1)
            level = _cap_level(distinct.index(size) + 1 if size in distinct else 1)
        headings.append(
            Heading(
                title=normalise_title(block.text)[:200],
                page=block.page,
                level=level,
                block_id=block.id,
            )
        )
    return headings


def _match_block(heading: Heading, blocks: list[Block], used: set[str]) -> Block | None:
    """Find the block that renders a bookmark's title on its page."""
    target = normalise_title(heading.title)
    same_page = [b for b in blocks if b.page == heading.page and b.id not in used]
    for block in same_page:
        if normalise_title(block.text) == target:
            return block
    # Bookmarks often differ from the rendered text only by numbering or case.
    stem = _NUMBERED.sub(r"\2", target).lower()
    for block in same_page:
        text = normalise_title(block.text).lower()
        if text == target.lower() or _NUMBERED.sub(r"\2", text) == stem:
            return block
    return None


def _assign_ids(headings: list[Heading], blocks: list[Block]) -> None:
    """Attach every heading to a block and give it a section id.

    Blocks that no heading matched keep the preceding section, so a bookmark
    list that misses a subsection does not orphan the text under it.
    """
    used: set[str] = set()
    for index, heading in enumerate(headings):
        block = _match_block(heading, blocks, used)
        if block is not None:
            heading.block_id = block.id
            used.add(block.id)
        heading.block_id = heading.block_id or ""
        heading.id = f"h{index + 1}"


def _fill_section_ids(headings: list[Heading], blocks: list[Block]) -> None:
    """Walk the blocks in reading order and assign each to the last heading."""
    if not headings:
        return
    by_block = {h.block_id: h for h in headings if h.block_id}
    current = headings[0]
    for block in blocks:
        if block.id in by_block:
            current = by_block[block.id]
            block.section_id = current.id
            block.type = "heading"
        else:
            block.section_id = current.id


def build_outline(
    doc: pdfio.Document,
    blocks: list[Block],
    body_size: float,
    sizes: dict[str, float] | None = None,
) -> list[OutlineItem]:
    """The heading tree for a document (T2.1).

    Bookmarks win. Without them, font-size and numbering rules decide. Either
    way the result is at most three levels deep and every entry carries the
    block it points at, so the reader can scroll to it.
    """
    headings = from_bookmarks(doc)
    source = "bookmarks"
    if not headings:
        headings = from_blocks(blocks, body_size, sizes or {})
        source = "rules"
    headings = _merge_wrapped(headings)

    _assign_ids(headings, blocks)
    _fill_section_ids(headings, blocks)
    logger.info("outline from %s: %d headings", source, len(headings))

    return [
        OutlineItem(
            id=heading.id or f"h{index + 1}",
            level=heading.level,
            title=heading.title[:200],
            page=heading.page,
            block_id=heading.block_id,
        )
        for index, heading in enumerate(headings)
    ]
