"""Figure sandbox entry point (H09).

The child runs a matplotlib script with no network, no file/exec builtins and
an import whitelist; this wrapper adds the wall-clock and RSS limits and turns
the child's result file into a structured outcome for the API.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .process import run_limited

RUNNER = Path(__file__).with_name("runner.py")
MAX_IMAGE_BYTES = 8 * 1024 * 1024
_KEEP_ENV = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT")


@dataclass(frozen=True)
class SandboxResult:
    ok: bool
    image: bytes | None
    error: str | None


def sandbox_env(work: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    """A minimal environment: the parent's secrets must not enter the sandbox."""
    env = {name: os.environ[name] for name in _KEEP_ENV if name in os.environ}
    temp = work / "tmp"
    temp.mkdir(exist_ok=True)
    env.update(
        {
            "TEMP": str(temp),
            "TMP": str(temp),
            "HOME": str(work),
            "USERPROFILE": str(work),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }
    )
    if extra:
        env.update(extra)
    return env


def _payload(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def run_python(script: str, *, timeout_s: float = 20.0, memory_mb: int = 512) -> SandboxResult:
    with tempfile.TemporaryDirectory(prefix="figure-sandbox-") as raw:
        work = Path(raw)
        config = work / "mpl"
        config.mkdir()
        script_path = work / "figure.py"
        script_path.write_text(script, "utf-8")
        output_path = work / "figure.png"
        result_path = work / "result.json"
        env = sandbox_env(work, {"MPLBACKEND": "Agg", "MPLCONFIGDIR": str(config)})
        command = [
            sys.executable,
            "-I",
            str(RUNNER),
            str(script_path),
            str(output_path),
            str(result_path),
        ]
        proc = run_limited(command, cwd=work, timeout_s=timeout_s, memory_mb=memory_mb, env=env)
        if proc.reason == "timeout":
            return SandboxResult(False, None, f"脚本运行超过 {timeout_s:g} 秒，已终止")
        if proc.reason == "memory":
            return SandboxResult(False, None, f"脚本内存超过 {memory_mb} MB，已终止")
        payload = _payload(result_path)
        if payload is None:
            detail = (proc.stderr or proc.stdout).strip()[:1500]
            suffix = f"：{detail}" if detail else ""
            return SandboxResult(False, None, f"沙箱进程异常退出（code={proc.returncode}）{suffix}")
        if not payload.get("ok"):
            return SandboxResult(False, None, str(payload.get("error") or "脚本运行失败"))
        if not output_path.is_file():
            return SandboxResult(False, None, "脚本没有生成图片")
        image = output_path.read_bytes()
        if not image.startswith(b"\x89PNG\r\n\x1a\n"):
            return SandboxResult(False, None, "沙箱输出不是 PNG")
        if len(image) > MAX_IMAGE_BYTES:
            return SandboxResult(False, None, "图片超过 8 MB，请简化图或降低 DPI")
        return SandboxResult(True, image, None)


__all__ = ["SandboxResult", "run_python", "sandbox_env"]
