"""Figure script endpoints (01 §5.6, T7.2).

`generate` produces a script, renders it and repairs it up to three times;
`run` renders a caller-supplied script without an LLM. Both return
`FigureResult`-shaped payloads; a failed script is a structured `errors` entry,
not an HTTP error, while an unavailable model is a 502 (H08).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..errors import AppError, InvalidRequest
from ..figures.prompts import MAX_DESCRIPTION
from ..figures.service import generate_figure, run_script
from ..figures.validate import MAX_SCRIPT_CHARS, FigureKind
from ..llm.errors import LLMError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["figures"])


class GenerateBody(BaseModel):
    kind: FigureKind
    description: str = Field(min_length=1, max_length=MAX_DESCRIPTION)


class RunBody(BaseModel):
    kind: FigureKind
    script: str = Field(min_length=1, max_length=MAX_SCRIPT_CHARS)


@router.post("/figures/generate")
async def generate(body: GenerateBody) -> dict[str, Any]:
    description = body.description.strip()
    if not description:
        raise InvalidRequest("图描述不能为空")
    try:
        return await generate_figure(body.kind, description)
    except LLMError as exc:
        logger.warning("figure generation: LLM unavailable: %s", exc)
        raise AppError(
            "图脚本生成失败：语言模型暂时不可用，请稍后重试",
            code="llm_unavailable",
            status_code=502,
        ) from exc


@router.post("/figures/run")
async def run(body: RunBody) -> dict[str, Any]:
    script = body.script.strip()
    if not script:
        raise InvalidRequest("脚本不能为空")
    return await run_script(body.kind, script)
