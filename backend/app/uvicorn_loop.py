"""Uvicorn loop factory that works with psycopg's async driver on Windows.

uvicorn 0.54's built-in ``asyncio`` factory returns ProactorEventLoop on
Windows, which psycopg cannot use ("InterfaceError"). A custom loop import
string is used as the factory directly (it is called with no arguments), so
this function must return a loop instance, not a loop class.
"""

from __future__ import annotations

import asyncio
import sys


def selector_loop_factory() -> asyncio.AbstractEventLoop:
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop()
    return asyncio.new_event_loop()
