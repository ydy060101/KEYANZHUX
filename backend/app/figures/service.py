"""Generate → render → repair loop for figure scripts (T7.2).

Initial generation uses the strong model. A failed validation or render is fed
back once per attempt, at most three times; a repair that returns the same
script stops the loop instead of spending the remaining attempts on a cached
answer. LLM unavailability during a repair keeps the last script and reports
the failure rather than discarding the work.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..llm.errors import LLMError
from ..llm.gateway import get_gateway
from .prompts import FigureScript, fix_messages, generation_messages
from .render import RenderOutcome, render_figure
from .validate import FigureKind, clean_script

logger = logging.getLogger(__name__)

MAX_FIXES = 3


def _payload(
    kind: FigureKind, script: str, outcome: RenderOutcome, attempts: int, extra_notes: list[str] | None = None
) -> dict[str, Any]:
    return {
        "kind": kind,
        "script": script,
        "rendered": outcome.rendered,
        "errors": outcome.errors,
        "notes": [*outcome.notes, *(extra_notes or [])],
        "renderer": outcome.renderer,
        "attempts": attempts,
    }


async def generate_figure(kind: FigureKind, description: str) -> dict[str, Any]:
    gateway = get_gateway()
    draft = await gateway.chat_json(
        generation_messages(kind, description),
        FigureScript,
        tier="strong",
        temperature=0.0,
        cache_prefix=f"figures:generate:{kind}:v1",
    )
    script = clean_script(kind, draft.script)
    last_error = ""

    for attempt in range(MAX_FIXES + 1):
        outcome = await asyncio.to_thread(render_figure, kind, script)
        if not outcome.errors:
            notes = [f"自动修复 {attempt} 次后渲染成功"] if attempt else []
            return _payload(kind, script, outcome, attempt, notes)
        last_error = "\n".join(outcome.errors)
        if attempt == MAX_FIXES:
            break
        try:
            fixed = await gateway.chat_json(
                fix_messages(kind, description, script, last_error),
                FigureScript,
                tier="fast",
                temperature=0.0,
                cache_prefix=f"figures:fix:{kind}:v1",
            )
        except LLMError as exc:
            logger.warning("figure repair: LLM unavailable: %s", exc)
            return _payload(
                kind,
                script,
                RenderOutcome(None, [last_error], [], outcome.renderer),
                attempt,
                ["自动修复中断：语言模型暂时不可用"],
            )
        repaired = clean_script(kind, fixed.script)
        if repaired == script:
            return _payload(
                kind,
                script,
                RenderOutcome(None, [last_error], [], outcome.renderer),
                attempt,
                ["模型未修改脚本，已停止自动修复"],
            )
        script = repaired

    return _payload(
        kind,
        script,
        RenderOutcome(None, [last_error], [], kind),
        MAX_FIXES,
        [f"已自动修复 {MAX_FIXES} 次仍未通过，请查看错误与最后一版脚本"],
    )


async def run_script(kind: FigureKind, script: str) -> dict[str, Any]:
    outcome = await asyncio.to_thread(render_figure, kind, script)
    return _payload(kind, script, outcome, 0)


__all__ = ["MAX_FIXES", "generate_figure", "run_script"]
