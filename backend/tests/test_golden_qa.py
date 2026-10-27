"""The golden set is data, so it is tested like data.

T3.6 requires the expected answers to be verified by a human against the
original. Until then this module enforces the properties that make that
verification meaningful: the set has the card's twenty questions, every id is
unique, and every expected point really does occur on one of the pages the
entry names. A typo in a needle or a page number fails here instead of silently
turning into a "miss" in `tools/check_qa.py`.

This checks the *fixture*, never the system's output, so it cannot be used to
tune an answer (H05).
"""

from __future__ import annotations

from typing import Any

from qa_support import load_golden


def test_the_set_has_twenty_single_document_questions() -> None:
    golden = load_golden()
    entries = golden["entries"]
    assert len(entries) == 20, len(entries)
    assert all(entry["scope"] == "single" for entry in entries)
    assert all(entry["question"].strip() for entry in entries)


def test_the_unanswerable_questions_are_named_and_justified() -> None:
    unanswerable = load_golden()["unanswerable"]
    assert len(unanswerable) >= 5
    assert all(item["question"].strip() and item["reason"].strip() for item in unanswerable)


def test_ids_are_unique() -> None:
    golden = load_golden()
    ids = [entry["id"] for entry in golden["entries"] + golden["unanswerable"]]
    assert len(ids) == len(set(ids))


def test_every_expected_point_occurs_on_an_expected_page(paper_parse: Any) -> None:
    by_page: dict[int, list[str]] = {}
    for block in paper_parse.model.blocks:
        by_page.setdefault(block.page, []).append(block.text or "")
    for entry in load_golden()["entries"]:
        pages = entry["expected_pages"]
        assert pages, entry["id"]
        text = " ".join(" ".join(by_page.get(page, [])) for page in pages).lower()
        for point in entry["expected_points"]:
            assert point.lower() in text, f"{entry['id']}: {point!r} not on pages {pages}"
