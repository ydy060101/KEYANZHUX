"""Job kind → handler registry.

`app.workers.tasks` registers every handler at import time. Keeping the
registry in its own module lets the API, the arq worker and tests share it
without importing the task implementations (and their heavy dependencies).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

Handler = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any] | None]]

_HANDLERS: dict[str, Handler] = {}


def register_handler(kind: str, handler: Handler) -> None:
    _HANDLERS[kind] = handler


def get_handler(kind: str) -> Handler | None:
    return _HANDLERS.get(kind)


def known_kinds() -> list[str]:
    return sorted(_HANDLERS)
