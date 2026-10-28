"""Sandbox child process for matplotlib scripts (H09).

Executed as `python -I runner.py <script> <png> <result.json>`. The script runs
with a restricted import hook and without file/exec builtins; sockets are
disabled before matplotlib is imported. The parent enforces the wall clock and
RSS ceiling and kills this process; this file only enforces capabilities.
"""

from __future__ import annotations

import builtins
import json
import random
import socket
import sys
from pathlib import Path
from typing import Any

MAX_SCRIPT_CHARS = 20_000
ALLOWED_ROOTS = frozenset(
    {
        "numpy",
        "pandas",
        "matplotlib",
        "graphviz",
        "math",
        "statistics",
        "random",
        "itertools",
        "functools",
        "collections",
        "re",
        "textwrap",
        "string",
        "decimal",
        "fractions",
        "json",
        "csv",
        "datetime",
        "typing",
    }
)
REMOVED_BUILTINS = (
    "open",
    "eval",
    "exec",
    "compile",
    "input",
    "breakpoint",
    "exit",
    "quit",
    "help",
    "globals",
    "locals",
    "vars",
    "getattr",
    "setattr",
    "delattr",
)


def _blocked(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError("沙箱内禁止网络访问")


def _block_network() -> None:
    for name in ("socket", "create_connection", "getaddrinfo", "gethostbyname"):
        if hasattr(socket, name):
            setattr(socket, name, _blocked)


def _guarded_import(
    name: str,
    globals_: dict[str, Any] | None = None,
    locals_: dict[str, Any] | None = None,
    fromlist: tuple[str, ...] = (),
    level: int = 0,
) -> Any:
    root = name.split(".")[0]
    if level or root not in ALLOWED_ROOTS:
        raise ImportError(f"模块 {root!r} 不在沙箱白名单内")
    return builtins.__import__(name, globals_, locals_, fromlist, level)


def _safe_builtins() -> dict[str, Any]:
    safe = dict(vars(builtins))
    safe["__import__"] = _guarded_import
    for name in REMOVED_BUILTINS:
        safe.pop(name, None)
    return safe


def _write_result(path: Path, ok: bool, error: str | None, figures: int) -> None:
    path.write_text(json.dumps({"ok": ok, "error": error, "figures": figures}, ensure_ascii=False), "utf-8")


def run(script_path: Path, output_path: Path, result_path: Path) -> None:
    script = script_path.read_text("utf-8")
    if len(script) > MAX_SCRIPT_CHARS:
        _write_result(result_path, False, f"脚本超过 {MAX_SCRIPT_CHARS} 字符", 0)
        return
    _block_network()
    random.seed(0)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    np.random.seed(0)
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    try:
        code = compile(script, "<figure>", "exec")
        exec(code, {"__builtins__": _safe_builtins(), "__name__": "__figure__"})
        numbers = list(plt.get_fignums())
        if not numbers:
            raise RuntimeError("脚本没有留下任何打开的图（不要调用 plt.close()）")
        plt.figure(numbers[-1]).savefig(output_path, dpi=150, bbox_inches="tight", facecolor="white")
        _write_result(result_path, True, None, len(numbers))
    except BaseException as exc:  # a script's SystemExit is still a script error
        message = f"{type(exc).__name__}: {exc}"[:3000]
        _write_result(result_path, False, message, 0)


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("usage: runner.py <script> <out.png> <result.json>")
    run(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))


if __name__ == "__main__":
    main()
