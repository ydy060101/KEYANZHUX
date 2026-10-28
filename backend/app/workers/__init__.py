"""Worker package.

`register_all()` imports the task modules, whose import side effect registers
their handlers. It is called from the API factory and the arq worker startup so
both processes know the same set of job kinds.
"""

from __future__ import annotations


def register_all() -> None:
    from . import embed_task, import_task, parse_task, translate_task  # noqa: F401
