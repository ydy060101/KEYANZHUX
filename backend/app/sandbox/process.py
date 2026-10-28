"""Bounded subprocess execution for the figure sandbox (H09).

Every child gets a wall-clock deadline and an RSS ceiling sampled from the
parent. `taskkill /T` is used on Windows so a tree spawned by a tool (for
example a TeX engine) cannot outlive the timeout.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO

import psutil

POLL_S = 0.05
MAX_OUTPUT = 8000


@dataclass(frozen=True)
class LimitedResult:
    returncode: int | None
    stdout: str
    stderr: str
    reason: str | None


def _kill(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    else:
        proc.kill()


def _read(handle: IO[bytes]) -> str:
    handle.seek(0)
    return handle.read(MAX_OUTPUT).decode("utf-8", "replace")


def _tree_rss(process: psutil.Process) -> int:
    """RSS of the whole tree: the venv launcher is a separate 5 MB process and
    the real interpreter (which owns the script's allocations) is its child."""
    try:
        total = int(process.memory_info().rss)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        total = 0
    try:
        for child in process.children(recursive=True):
            try:
                total += int(child.memory_info().rss)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return total


def run_limited(
    command: list[str],
    *,
    cwd: Path,
    timeout_s: float,
    memory_mb: int,
    env: dict[str, str] | None = None,
) -> LimitedResult:
    """Run `command`; kill it on timeout or when RSS exceeds `memory_mb`."""
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        proc = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            tracked: psutil.Process | None = psutil.Process(proc.pid)
        except psutil.NoSuchProcess:  # the child exited before we sampled it
            tracked = None
        limit = memory_mb * 1024 * 1024
        deadline = time.monotonic() + timeout_s
        reason: str | None = None
        while proc.poll() is None:
            if tracked is not None and _tree_rss(tracked) > limit:
                reason = "memory"
                _kill(proc)
                break
            if time.monotonic() >= deadline:
                reason = "timeout"
                _kill(proc)
                break
            time.sleep(POLL_S)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - taskkill races
            _kill(proc)
            proc.wait()
        return LimitedResult(proc.returncode, _read(stdout), _read(stderr), reason)


__all__ = ["LimitedResult", "run_limited"]
