"""Targeted extraction for metadata questions (01 §9).

01 §9: "元数据型问题（作者机构、超参数、GPU 型号数量、BLEU、指定引用的完整
信息）：先走'定向抽取'——在相关章节 chunk 内用 JSON 模式抽取字段，并强制返回
anchor；抽不到则返回 null."

The extraction is not trusted on its own. A field survives only when its value
occurs literally in the block it names (H02, H04); anything else becomes a null
field, and the generator never sees it. The fields are then handed to the
answer prompt as checked facts, which is what makes a hyperparameter question
more reliable than free generation over the same eight chunks.

Extraction uses the `fast` tier, as 01 §6 assigns "字段抽取" to it. A gateway
failure is degraded, not fatal (H08): the answer is generated without the
facts section.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from ..llm.errors import LLMError
from .prompt import Evidence, extraction_messages
from .verify import contains

logger = logging.getLogger(__name__)

# Cues that the question is asking for named fields rather than an explanation.
# Over-triggering costs one fast-tier call; under-triggering loses the
# grounding benefit on exactly the questions that need it most.
_METADATA_CUES = [
    r"\bauthors?\b",
    r"\baffiliations?\b",
    r"\binstitutions?\b",
    r"\buniversit(?:y|ies)\b",
    r"\bcompanies\b",
    r"\bhyper-?parameters?\b",
    r"\blearning rate\b",
    r"\bbatch size\b",
    r"\boptimizer\b",
    r"\bdropout\b",
    r"\bwarm-?up\b",
    r"\b(?:layers?|heads?|dimensions?)\b",
    r"\bhow many\b",
    r"\bgpus?\b",
    r"\btpus?\b",
    r"\bhardware\b",
    r"\bbleu\b",
    r"\b(?:accuracy|f1|perplexity)\b",
    r"\bwhich (?:paper|reference|citation)\b",
    r"\breferences?\b",
    r"\b(?:training|test) (?:time|cost|data)\b",
]
_CUE = re.compile("|".join(_METADATA_CUES), re.IGNORECASE)
MAX_FIELDS = 8
MAX_VALUE = 120


class ExtractedField(BaseModel):
    name: str
    value: str | None = None
    evidence: int | None = Field(default=None, description="1-based evidence number")


class Extraction(BaseModel):
    fields: list[ExtractedField] = Field(default_factory=list)


def is_metadata_question(question: str) -> bool:
    return _CUE.search(question) is not None


async def extract_fields(gateway: Any, question: str, evidence: list[Evidence]) -> list[ExtractedField]:
    """Fields named by the question, each kept only if grounded in its block.

    The return value includes the nulled fields on purpose: a caller can then
    show "asked for X, not found" rather than silently omitting it, and the
    test suite can tell "the model returned nothing" from "the model returned
    something that did not survive verification".
    """
    if not evidence:
        return []
    try:
        result = await gateway.chat_json(extraction_messages(question, evidence), Extraction, tier="fast")
    except LLMError as exc:
        logger.warning("targeted extraction failed: %s", exc)
        return []
    fields: list[ExtractedField] = []
    for item in result.fields[:MAX_FIELDS]:
        fields.append(_checked(item, evidence))
    return fields


def _checked(field: ExtractedField, evidence: list[Evidence]) -> ExtractedField:
    """The field if its value is literally in the block it cites, else null."""
    name = field.name.strip()[:80]
    value = (field.value or "").strip()[:MAX_VALUE]
    number = field.evidence
    if not value or number is None or not 1 <= number <= len(evidence):
        return ExtractedField(name=name, value=None, evidence=None)
    if not contains(evidence[number - 1].text, value):
        logger.info("extracted field %r not found in evidence [%s]; nulled", name, number)
        return ExtractedField(name=name, value=None, evidence=None)
    return ExtractedField(name=name, value=value, evidence=number)
