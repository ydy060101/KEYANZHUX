"""The golden set is data, so it is tested like data.

T3.6 requires the expected answers to be verified by a human against the
original. Until then this module enforces the properties that make that
verification meaningful: the set has the card's twenty single-document
questions and ten cross-document ones, every id is unique, and every expected
point really does occur on one of the pages the entry names. A typo in a needle
or a page number fails here instead of silently turning into a "miss" in
`tools/check_qa.py`. An entry may also expect a document to be **silent** on a
dimension (`absent` + `not_in`); that asserts the strings really do not occur
anywhere in the paper, so the compare path can be tested for saying
"未在原文找到" when the source has nothing.

This checks the *fixture*, never the system's output, so it cannot be used to
tune an answer (H05).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from qa_support import load_golden

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "pdf"


def _pages(filename: str) -> dict[int, str]:
    from app.ingest.parser import parse_pdf

    path = FIXTURES / filename
    if not path.is_file():
        pytest.skip(f"{filename} is not staged")
    model = parse_pdf(path, f"golden-{path.stem}").model
    by_page: dict[int, list[str]] = {}
    for block in model.blocks:
        by_page.setdefault(block.page, []).append(block.text or "")
    return {page: " ".join(texts) for page, texts in by_page.items()}


@pytest.fixture(scope="module")
def document_pages() -> dict[str, dict[int, str]]:
    return {
        key: _pages(info["fixture"]) for key, info in load_golden()["documents"].items()
    }


def test_the_set_has_twenty_single_document_questions() -> None:
    golden = load_golden()
    entries = golden["entries"]
    assert len(entries) == 20, len(entries)
    assert all(entry["scope"] == "single" for entry in entries)
    assert all(entry["question"].strip() for entry in entries)


def test_the_cross_set_has_ten_three_paper_questions() -> None:
    cross = load_golden()["cross"]
    assert len(cross) == 10
    for entry in cross:
        assert entry["scope"] == "cross"
        assert entry["dimensions"], entry["id"]
        assert set(entry["expected"]) == {"transformer", "bert", "gpt3"}, entry["id"]


def test_the_unanswerable_questions_are_named_and_justified() -> None:
    unanswerable = load_golden()["unanswerable"]
    assert len(unanswerable) >= 5
    assert all(item["question"].strip() and item["reason"].strip() for item in unanswerable)


def test_ids_are_unique() -> None:
    golden = load_golden()
    ids = [entry["id"] for entry in golden["entries"] + golden["unanswerable"] + golden["cross"]]
    assert len(ids) == len(set(ids))


def test_every_expected_point_occurs_on_an_expected_page(document_pages: dict[str, Any]) -> None:
    for entry in load_golden()["entries"]:
        pages = entry["expected_pages"]
        assert pages, entry["id"]
        fixture = document_pages[entry["doc"]]
        text = " ".join(fixture.get(page, "") for page in pages).lower()
        for point in entry["expected_points"]:
            assert point.lower() in text, f"{entry['id']}: {point!r} not on pages {pages}"


def test_every_cross_expectation_matches_its_fixture(document_pages: dict[str, Any]) -> None:
    for entry in load_golden()["cross"]:
        for doc, expected in entry["expected"].items():
            fixture = document_pages[doc]
            if expected.get("absent"):
                whole = " ".join(fixture.values()).lower()
                for term in expected["not_in"]:
                    assert term.lower() not in whole, (
                        f"{entry['id']}: {doc} unexpectedly contains {term!r}"
                    )
                continue
            pages = expected["pages"]
            text = " ".join(fixture.get(page, "") for page in pages).lower()
            for point in expected["points"]:
                assert point.lower() in text, f"{entry['id']}: {doc} {point!r} not on {pages}"
