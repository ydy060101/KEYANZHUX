"""LLM gateway — the only place that talks to a model provider (01 §6)."""

from __future__ import annotations

from .gateway import LLMGateway, get_gateway
from .types import ChatResult, Tier

__all__ = ["ChatResult", "Tier", "LLMGateway", "get_gateway"]
