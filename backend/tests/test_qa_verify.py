"""H04 mechanics: sentence splitting, token extraction and literal verification.

These are pure functions, so no database and no gateway. The pipeline tests in
`test_qa.py` use them through `run_qa`.
"""

from __future__ import annotations

from app.qa.prompt import Evidence
from app.qa.verify import (
    contains,
    grounds,
    is_not_found,
    parse_markers,
    split_sentences,
    verifiable_tokens,
    verify_answer,
)


def ev(number: int, text: str) -> Evidence:
    return Evidence(
        number=number,
        chunk_id=f"c{number}",
        doc_id="doc",
        doc_title="A Paper",
        page_start=1,
        page_end=1,
        text=text,
        block_ids=(f"b{number}",),
    )


def test_sentences_split_without_breaking_decimals_or_abbreviations() -> None:
    text = "We trained for 3.5 days, i.e. 300K steps. The big model used 16 heads."
    assert split_sentences(text) == [
        "We trained for 3.5 days, i.e. 300K steps.",
        "The big model used 16 heads.",
    ]


def test_chinese_punctuation_ends_a_sentence() -> None:
    assert split_sentences("它使用 8 个头。编码器有 6 层。") == ["它使用 8 个头。", "编码器有 6 层。"]


def test_markers_parse_lists_and_dedupe() -> None:
    assert parse_markers("A [1, 2][3] and again [1].") == [1, 2, 3]


def test_tokens_include_numbers_names_and_formulas() -> None:
    tokens = verifiable_tokens("BERT uses 8 heads and $d_k = 64$ with Adam.")
    assert "BERT" in tokens
    assert "8" in tokens
    assert "d_k = 64" in tokens
    assert "Adam" in tokens
    assert "uses" not in tokens


def test_ordinary_capitalised_words_are_not_tokens() -> None:
    tokens = verifiable_tokens("The model is trained in Table 2.")
    assert "The" not in tokens
    assert "Table" not in tokens


def test_comparison_normalises_dashes_and_space_but_not_letters() -> None:
    assert contains("value ϵ = 10−9 here", "10-9")
    assert contains("dropout  Pdrop = 0.1", "Pdrop = 0.1")
    assert not contains("Adam optimizer", "adam")


def test_a_number_is_only_grounded_as_a_whole_token() -> None:
    row = "GPT-3 175B 96 12288 96 128 3.2M"
    assert grounds(row, "96")
    assert grounds(row, "12288")
    assert not grounds(row, "12")  # a prefix of 12288
    assert not grounds(row, "1228")  # a prefix of 12288
    assert grounds(row, "175")  # the number part of 175B, a unit suffix
    assert grounds(row, "175B")


def test_grounding_accepts_sentence_punctuation_but_not_decimals() -> None:
    assert grounds("The base model uses 512.", "512")
    assert grounds("H=768 and A=12", "12")
    assert not grounds("H=768", "76")
    assert not grounds("a rate of 12.5", "12")
    assert grounds("a rate of 12.5", "12.5")
    assert not grounds("N = 6", "N=6")


def test_not_found_sentinel_allows_trailing_punctuation() -> None:
    assert is_not_found("NOT_FOUND")
    assert is_not_found(" NOT_FOUND. ")
    assert not is_not_found("The answer is NOT_FOUND for this question")


def test_grounded_sentence_survives_and_others_are_flagged() -> None:
    evidence = [ev(1, "We use warmup_steps = 4000 training steps.")]
    raw = "The model uses 4000 warmup steps [1]. It is very good. It uses 5000 steps [1]."
    result = verify_answer(raw, evidence)
    assert [sentence.text for sentence in result.sentences] == ["The model uses 4000 warmup steps [1]."]
    kinds = [flag.kind for flag in result.flags]
    assert "uncited_claim" in kinds
    assert "ungrounded_number" in kinds
    assert any("5000" in flag.text for flag in result.flags)


def test_a_fabricated_name_drops_the_sentence() -> None:
    evidence = [ev(1, "Attention is computed with eight heads.")]
    result = verify_answer("Attention uses Copernicus routing [1].", evidence)
    assert result.sentences == []
    assert any("Copernicus" in flag.text for flag in result.flags)


def test_an_out_of_range_marker_is_removed_but_the_sentence_stays() -> None:
    evidence = [ev(1, "We use warmup_steps = 4000 training steps.")]
    result = verify_answer("The schedule uses 4000 steps [1][9].", evidence)
    assert [sentence.text for sentence in result.sentences] == ["The schedule uses 4000 steps [1]."]
    assert any(flag.kind == "invalid_citation" and "9" in flag.text for flag in result.flags)


def test_only_uncited_sentences_is_a_refusal_not_an_answer() -> None:
    evidence = [ev(1, "We use warmup_steps = 4000 training steps.")]
    result = verify_answer("The model is good.", evidence)
    assert result.sentences == []
    assert result.flags


def test_quotes_are_at_most_two_hundred_characters() -> None:
    body = ("padding " * 40) + "warmup_steps = 4000 " + ("tail " * 40)
    evidence = [ev(1, body)]
    result = verify_answer("The schedule uses 4000 steps [1].", evidence)
    quote = result.sentences[0].quotes[1]
    assert len(quote) <= 200
    assert "4000" in quote


def test_the_quote_centres_on_the_rarest_token() -> None:
    """A token that occurs once locates its sentence better than a common one.

    The real q17 case: the chunk opens on page 6 with "WMT 2014 English-German"
    and the answer ("36M sentences") is on page 7. Quoting around the first
    token showed the wrong sentence.
    """
    text = (
        "We trained on the WMT 2014 English-German dataset. "
        + ("filler " * 40)
        + "The WMT 2014 English-French set has 36M sentences."
    )
    result = verify_answer("The WMT 2014 English-French set has 36M sentences [1].", [ev(1, text)])
    quote = result.sentences[0].quotes[1]
    assert "36M sentences" in quote
