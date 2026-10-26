"""Gateway errors."""

from __future__ import annotations


class LLMError(Exception):
    """Base class for gateway failures."""


class LLMTimeout(LLMError):
    pass


class LLMRateLimited(LLMError):
    pass


class LLMUnavailable(LLMError):
    pass


class LLMSchemaViolation(LLMError):
    """Structured output failed Pydantic validation after a retry."""


class FeatureDisabled(LLMError):
    """Raised when a disabled capability (e.g. vision) is requested."""
