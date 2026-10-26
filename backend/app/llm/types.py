"""Shared types for the LLM layer."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Tier = Literal["fast", "strong"]


class ChatResult(BaseModel):
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached: bool = False
    latency_ms: float = 0.0
