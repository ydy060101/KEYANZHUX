"""T2.1 acceptance: the heading tree matches the printed table of contents."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ingest import pdfio
from app.ingest.outline import MAX_LEVEL, build_outline, from_blocks, normalise_title
from app.ingest.parser import parse_pdf
from app.models.schemas import Block

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "pdf"


@pytest.fixture(scope="module")
def transformer() -> list[tuple[int, str]]:
    model = parse_pdf(FIXTURES / "1706.03762v1.pdf", "doc-t").model
    return [(item.level, item.title) for item in model.outline]


def test_transformer_uses_its_embedded_outline(transformer: list[tuple[int, str]]) -> None:
    """The PDF has bookmarks, so the tree must be exactly what they say."""
    titles = [title for _level, title in transformer]
    assert titles[:3] == ["1 Introduction", "2 Background", "3 Model Architecture"]
    assert "3.2.1 Scaled Dot-Product Attention" in titles
    assert "5.4 Regularization" in titles


def test_transformer_three_levels_are_correct(transformer: list[tuple[int, str]]) -> None:
    by_title = dict((title, level) for level, title in transformer)
    assert by_title["3 Model Architecture"] == 1
    assert by_title["3.2 Attention"] == 2
    assert by_title["3.2.2 Multi-Head Attention"] == 3


def test_no_outline_exceeds_three_levels(transformer: list[tuple[int, str]]) -> None:
    assert max(level for level, _title in transformer) <= MAX_LEVEL


def test_bert_without_bookmarks_uses_font_and_numbering_rules() -> None:
    """BERT ships no outline; the rules must still recover its real sections."""
    model = parse_pdf(FIXTURES / "1810.04805_bert.pdf", "doc-b").model
    titles = [item.title for item in model.outline]
    assert "1 Introduction" in titles
    assert "2 Related Work" in titles
    assert "6 Conclusion" in titles
    # Figure labels are bold and short, but they are not in the tree.
    assert not any("Masked Sentence" in title for title in titles)
    assert not any("PositionEmbeddings" in title for title in titles)


def test_bert_numbering_is_restored_where_the_pdf_drops_the_space() -> None:
    """BERT extracts "1Introduction"; the tree must read "1 Introduction"."""
    model = parse_pdf(FIXTURES / "1810.04805_bert.pdf", "doc-b").model
    titles = [item.title for item in model.outline]
    assert "1Introduction" not in titles
    assert "3.1Pre-training BERT" not in titles


def test_bert_wrapped_title_is_one_entry() -> None:
    model = parse_pdf(FIXTURES / "1810.04805_bert.pdf", "doc-b").model
    titles = [item.title for item in model.outline]
    joined = [title for title in titles if title.startswith("BERT: Pre-training")]
    assert len(joined) == 1, "a wrapped title must not become two headings"
    assert joined[0].endswith("Language Understanding")


def test_gpt3_outline_has_level_two_subsections() -> None:
    model = parse_pdf(FIXTURES / "2005.14165_gpt3.pdf", "doc-g").model
    by_title = {item.title: item.level for item in model.outline}
    assert by_title["2 Approach"] == 1
    assert by_title["2.1 Model and Architectures"] == 2


def test_every_outline_item_points_at_a_block(transformer: list[tuple[int, str]]) -> None:
    model = parse_pdf(FIXTURES / "1706.03762v1.pdf", "doc-t").model
    block_ids = {block.id for block in model.blocks}
    for item in model.outline:
        assert item.block_id in block_ids, f"{item.title} has no block"
        assert item.page >= 1


def test_blocks_after_a_heading_carry_its_section_id() -> None:
    model = parse_pdf(FIXTURES / "1706.03762v1.pdf", "doc-t").model
    headings = {item.block_id: item.id for item in model.outline}
    assert headings, "expected a heading tree"
    seen = 0
    for block in model.blocks:
        if block.section_id in set(headings.values()):
            seen += 1
    assert seen > 100, "body blocks must be attached to a section"


def test_normalise_title_handles_numbered_and_lettered_prefixes() -> None:
    assert normalise_title("3.2.1  Scaled  Dot-Product") == "3.2.1 Scaled Dot-Product"
    assert normalise_title("1Introduction") == "1 Introduction"
    assert normalise_title("AAdditional Details") == "A Additional Details"
    assert normalise_title("References") == "References"


def test_from_blocks_rejects_a_numbering_jump() -> None:
    """A figure label reading "1Introduction" mid-paper is not a heading."""
    blocks = [
        Block(id="b1", type="paragraph", page=1, bbox=[0, 0, 1, 1], reading_order=1, text="1 Introduction"),
        Block(id="b2", type="paragraph", page=2, bbox=[0, 0, 1, 1], reading_order=2, text="2 Method"),
        Block(id="b3", type="paragraph", page=3, bbox=[0, 0, 1, 1], reading_order=3, text="1Introduction"),
    ]
    headings = from_blocks(blocks, body_size=10.0, sizes={"b1": 12.0, "b2": 12.0, "b3": 12.0})
    assert [h.title for h in headings] == ["1 Introduction", "2 Method"]


def test_build_outline_falls_back_when_the_pdf_has_no_bookmarks() -> None:
    doc = pdfio.open_document(FIXTURES / "1810.04805_bert.pdf")
    try:
        assert pdfio.bookmarks(doc) == [], "BERT is expected to have no outline"
        blocks = [
            Block(id="b1", type="paragraph", page=1, bbox=[0, 0, 1, 1], reading_order=1, text="1 Introduction")
        ]
        outline = build_outline(doc, blocks, body_size=10.0, sizes={"b1": 12.0})
        assert [item.title for item in outline] == ["1 Introduction"]
    finally:
        pdfio.close_document(doc)
