"""H04: literal back-checking of an answer against the chunks it cites.

AGENTS.md H04 says: "回答中出现的数字、专有名词、公式必须能在所引 chunk 原文中
字面找到；找不到则该句删除或标注'未验证'". This module implements the deletion
path, at sentence granularity:

  * a sentence that cites nothing is dropped and flagged `uncited_claim`
    (H01: a conclusion without an anchor must not be output);
  * a citation number outside 1..n is dropped and flagged `invalid_citation`;
  * a sentence whose number, name or formula does not occur in the text of the
    evidence it cites is dropped and flagged `ungrounded_number`;
  * a reply of `NOT_FOUND` (the prompt's sentinel) is a refusal, not an answer.

The comparison normalises compatibility forms and dash variants but nothing
else: "1e-4" is not accepted for "10^-4", and "roughly 40" is not accepted for
"41.0". A number the model rounded has not been found in the source, which is
exactly what H04 is for.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .prompt import Evidence
from .schemas import QaFlag

MARKER = re.compile(r"\[\s*(\d+(?:\s*,\s*\d+)*)\s*\]")
NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*(?:[eE][-+]?\d+)?%?")
NAME = re.compile(r"\b[A-Z][A-Za-z0-9]*(?:[-'][A-Za-z0-9]+)*\b")
MATH = re.compile(r"\$([^$\n]+)\$")

# Sentence punctuation that ends a sentence when followed by a space and
# something that starts one. The abbreviation list stops "e.g. The model" from
# becoming two claims, the second of which would have lost its citation.
_ABBREVIATIONS = {
    "e.g.",
    "i.e.",
    "et al.",
    "al.",
    "fig.",
    "figs.",
    "eq.",
    "eqs.",
    "sec.",
    "ref.",
    "refs.",
    "no.",
    "vs.",
    "cf.",
    "approx.",
    "dr.",
}

# Capitalised words that are not proper nouns worth verifying. Sentence-initial
# position is *not* enough to skip a token: "BERT is ..." starts with the very
# name that must be checked.
_STOPWORDS = {
    "the", "a", "an", "this", "that", "these", "those", "it", "its", "they", "their",
    "there", "here", "we", "our", "you", "your", "i", "in", "on", "at", "by", "for",
    "from", "with", "without", "and", "or", "but", "if", "when", "which", "while",
    "who", "whom", "whose", "what", "where", "why", "how", "as", "to", "of", "is",
    "are", "was", "were", "be", "been", "being", "not", "no", "yes", "however",
    "moreover", "furthermore", "therefore", "thus", "additionally", "specifically",
    "first", "second", "third", "finally", "also", "both", "each", "every", "some",
    "any", "all", "only", "such", "than", "then", "so", "because", "although",
    "though", "since", "during", "after", "before", "between", "among", "per",
    "via", "using", "used", "use", "table", "figure", "fig", "section", "equation",
    "eq", "appendix", "algorithm", "chapter", "page", "pages", "paper", "one",
    "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "results", "result", "training", "model", "models", "abstract", "introduction",
    "conclusion", "reference", "references", "example", "note", "overall",
}  # fmt: skip


@dataclass
class VerifiedSentence:
    text: str
    markers: list[int]
    quotes: dict[int, str] = field(default_factory=dict)


@dataclass
class Verification:
    sentences: list[VerifiedSentence]
    flags: list[QaFlag]
    dropped: list[str]
    not_found: bool = False


def normalise(text: str) -> str:
    """Compat forms, dash variants and runs of whitespace folded, nothing more."""
    text = unicodedata.normalize("NFKC", text)
    for dash in ("‐", "‑", "‒", "–", "—", "−"):
        text = text.replace(dash, "-")
    text = text.replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip()


def contains(haystack: str, needle: str) -> bool:
    """Whether `needle` occurs literally in `haystack` after normalisation."""
    return bool(needle) and normalise(needle) in normalise(haystack)


def split_sentences(text: str) -> list[str]:
    """Sentence boundaries, without splitting "e.g. The model" or "3.5".

    A full stop is a boundary only when followed by whitespace and then
    something that can start a sentence (upper case, a digit, a CJK character,
    an opening quote). Chinese punctuation splits without needing the space.
    """
    text = text.strip()
    if not text:
        return []
    parts: list[str] = []
    start = 0
    index = 0
    while index < len(text):
        char = text[index]
        if char in "。！？":
            parts.append(text[start : index + 1])
            start = index + 1
        elif char in ".!?":
            after = index + 1
            while after < len(text) and text[after] in "\"'”’)":
                after += 1
            if after >= len(text):
                parts.append(text[start:after])
                start = after
            elif text[after].isspace():
                next_char = text[after:].lstrip()[:1]
                words = text[start : index + 1].split()
                last_word = words[-1].lower() if words else ""
                starts_sentence = bool(next_char) and (
                    next_char.isupper() or next_char.isdigit() or ord(next_char[0]) > 0x2E80
                )
                if last_word not in _ABBREVIATIONS and starts_sentence:
                    parts.append(text[start:after])
                    start = after
        index += 1
    if start < len(text):
        parts.append(text[start:])
    return [part.strip() for part in parts if part.strip()]


def parse_markers(sentence: str) -> list[int]:
    """Citation numbers in order of appearance, without duplicates."""
    numbers: list[int] = []
    for match in MARKER.finditer(sentence):
        for part in match.group(1).split(","):
            number = int(part.strip())
            if number not in numbers:
                numbers.append(number)
    return numbers


def verifiable_tokens(sentence: str) -> list[str]:
    """Numbers, names and formulas that must be found in the cited text."""
    tokens: list[str] = []
    prose = MARKER.sub(" ", sentence)
    for formula in MATH.findall(prose):
        tokens.append(formula.strip())
    prose = MATH.sub(" ", prose)
    tokens.extend(NUMBER.findall(prose))
    for match in NAME.finditer(prose):
        word = match.group(0)
        if len(word) < 2 or word.lower() in _STOPWORDS or word in tokens:
            continue
        tokens.append(word)
    return [token for token in tokens if token]


def is_not_found(raw: str) -> bool:
    """The prompt's sentinel, allowing trailing punctuation."""
    stripped = normalise(raw).upper()
    return re.fullmatch(r"NOT_FOUND[\s.!。！]*", stripped) is not None


def verify_answer(raw: str, evidence: list[Evidence]) -> Verification:
    """Split, check and filter an answer. `sentences` is what may be shown."""
    if is_not_found(raw):
        return Verification(
            sentences=[],
            flags=[QaFlag(kind="weak_support", text="模型判断所给证据未包含答案")],
            dropped=[raw],
            not_found=True,
        )
    if not raw.strip():
        return Verification(
            sentences=[],
            flags=[QaFlag(kind="weak_support", text="模型未返回任何内容")],
            dropped=[],
            not_found=False,
        )
    texts = {item.number: item.text for item in evidence}
    known = set(texts)
    sentences: list[VerifiedSentence] = []
    flags: list[QaFlag] = []
    dropped: list[str] = []
    for sentence in split_sentences(raw):
        cited = parse_markers(sentence)
        valid = [number for number in cited if number in known]
        invalid = [number for number in cited if number not in known]
        for number in invalid:
            flags.append(
                QaFlag(kind="invalid_citation", text=f"引用编号 [{number}] 不存在，已忽略：{sentence[:80]}")
            )
        if not valid:
            flags.append(QaFlag(kind="uncited_claim", text=f"句子未标注证据，已删除：{sentence[:120]}"))
            dropped.append(sentence)
            continue
        cited_text = " ".join(texts[number] for number in valid)
        tokens = verifiable_tokens(sentence)
        missing = [token for token in tokens if not contains(cited_text, token)]
        if missing:
            flags.append(
                QaFlag(
                    kind="ungrounded_number",
                    text=f"未在所引原文中找到 {', '.join(missing[:5])}，已删除：{sentence[:80]}",
                )
            )
            dropped.append(sentence)
            continue
        cleaned = _drop_markers(sentence, set(invalid)) if invalid else sentence
        quotes = {number: _quote(sentence, evidence[number - 1]) for number in valid}
        sentences.append(VerifiedSentence(text=cleaned.strip(), markers=valid, quotes=quotes))
    return Verification(sentences=sentences, flags=flags, dropped=dropped)


def _drop_markers(text: str, drop: set[int]) -> str:
    """Remove the numbers in `drop` from marker groups, keeping the rest."""

    def replace(match: re.Match[str]) -> str:
        kept = [int(part) for part in match.group(1).split(",") if int(part) not in drop]
        return f"[{','.join(str(number) for number in kept)}]" if kept else ""

    return MARKER.sub(replace, text)


def _quote(sentence: str, evidence: Evidence, limit: int = 200) -> str:
    """The evidence window around the most locating verified token.

    The rarest token is the one that identifies the passage: a number that
    occurs once points at its own sentence, while "Transformer" occurs on every
    page. The first version used the first token in the sentence, which on a
    question about the English-French set quoted the preceding sentence's
    "WMT 2014" and stopped before the "36M" that answers it.
    """
    text = evidence.text
    tokens = [token for token in verifiable_tokens(sentence) if token]
    if not tokens:
        return text.strip()[:limit]
    counts = {token: max(1, text.count(token)) for token in tokens}
    order = sorted(range(len(tokens)), key=lambda index: (counts[tokens[index]], index))
    for index in order:
        token = tokens[index]
        position = text.find(token)
        if position < 0:
            position = text.lower().find(token.lower())
        if position < 0:
            continue
        start = max(0, position - 50)
        if start > 0 and not text[start - 1].isspace():
            # Do not start the quote in the middle of a word.
            space = text.find(" ", start, position)
            start = space + 1 if space >= 0 else start
        return text[start : start + limit].strip()[:limit]
    return text.strip()[:limit]
