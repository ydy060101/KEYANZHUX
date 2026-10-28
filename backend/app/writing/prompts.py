"""Prompts and response models for the outline pipeline (T7.1).

Kept apart from the pipeline so the prompt text and the Pydantic shapes stay
reviewable on their own. `OutlineDraft` accepts both the nested `sections`
array the schema asks for and the top-level `abstract` / `introduction` /
`related_work` fields the provider actually returns.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from ..llm.safety import system_with_guard, wrap_data

HEADINGS = ("Abstract", "Introduction", "Related Work")
MAX_QUERIES = 5
MAX_IDEA = 4000


@dataclass(frozen=True)
class OutlineInput:
    idea: str
    language: str = "zh"
    venue: str | None = None


class SectionPlan(BaseModel):
    heading: str = ""
    goal: str = ""
    queries: list[str] = Field(default_factory=list)


class OutlinePlan(BaseModel):
    title: str
    sections: list[SectionPlan] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)


class SectionDraft(BaseModel):
    heading: str = ""
    markdown: str = ""


class OutlineDraft(BaseModel):
    """The model's natural shape: one field per required section.

    A nested `sections` array was ignored by the provider in practice (it
    returned `abstract`/`introduction`/`related_work` at the top level and an
    empty array), so both shapes are accepted and the named fields win.
    """

    title: str = ""
    abstract: str = ""
    introduction: str = ""
    related_work: str = ""
    sections: list[SectionDraft] = Field(default_factory=list)


def _language_line(language: str) -> str:
    return "Simplified Chinese" if language == "zh" else "academic English"


def plan_messages(idea: str, language: str, venue: str | None) -> list[dict[str, str]]:
    system = system_with_guard(
        "You plan the opening of a research paper: Abstract, Introduction and Related Work. "
        "Return JSON only. Sections are plans, not prose. Search queries must be specific "
        "paper-topic queries for bibliographic databases. Never invent a reference."
    )
    where = f"\nTarget venue: {venue}" if venue else ""
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": (
                "Plan the paper outline. The title must be a concise paper title in the prose "
                "language, not the raw idea.\n"
                f"Write the eventual prose in {_language_line(language)}.\n"
                "Use exactly these section headings: Abstract, Introduction, Related Work.\n"
                "Write the search queries in English even when the prose is Chinese, because "
                "bibliographic databases index English metadata. Each query must be a short "
                "keyword phrase of two to six words, never a sentence.\n"
                f"Give each section a goal and zero to three search queries, plus up to "
                f"{MAX_QUERIES} overall queries.\n\n"
                f"Idea:{where}\n{wrap_data(idea)}"
            ),
        },
    ]


def draft_messages(
    idea: str, language: str, venue: str | None, plan: OutlinePlan, references: Sequence[dict[str, Any]]
) -> list[dict[str, str]]:
    listed = "\n".join(
        f"- key={item['key']} | {item['title']} | {', '.join(item.get('authors') or [])} | {item.get('year') or 'n.d.'}"
        for item in references
    )
    if not listed:
        listed = "(none — no citation is available)"
    system = system_with_guard(
        "You write the first three sections of a research paper as Markdown. "
        "Citations use exactly \\cite{key}. Only keys from the verified list may be cited. "
        "Never name a paper, author, number or URL that is not in that list. "
        "When a citation would be needed and no verified key fits, write [待补充] instead. "
        "Do not invent results, datasets or metrics. This is a proposal framework, not a "
        "report: never claim that experiments were run or report findings; use future "
        'framing ("we will evaluate ..."). Return JSON with exactly four keys: '
        "title, abstract, introduction, related_work, and no nested sections object."
    )
    goals = "\n".join(f"- {section.heading}: {section.goal}" for section in plan.sections)
    where = f"\nVenue: {venue}" if venue else ""
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": (
                f"Write in {_language_line(language)}. Headings: Abstract, Introduction, Related Work.\n"
                "Return JSON keys title, abstract, introduction, related_work; each section is "
                "Markdown prose, not a list of headings.\n"
                f"Title: {plan.title}{where}\nSection goals:\n{goals}\n\n"
                f"Verified references (the only citable works):\n{wrap_data(listed)}\n\n"
                f"Idea:\n{wrap_data(idea)}"
            ),
        },
    ]


__all__ = [
    "HEADINGS",
    "MAX_IDEA",
    "MAX_QUERIES",
    "OutlineDraft",
    "OutlineInput",
    "OutlinePlan",
    "SectionDraft",
    "SectionPlan",
    "draft_messages",
    "plan_messages",
]
