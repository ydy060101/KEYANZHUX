"""T7.2 sandbox: a real PNG, the import whitelist and the resource limits."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.sandbox import run_python, sandbox_env

PLOT = """
import matplotlib.pyplot as plt

fig, ax = plt.subplots()
ax.plot([1, 2, 3], [1, 4, 9])
ax.set_title("sandbox")
"""


def test_python_script_renders_png() -> None:
    result = run_python(PLOT, timeout_s=30, memory_mb=512)
    assert result.ok, result.error
    assert result.image is not None
    assert result.image.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(result.image) > 1000


def test_import_outside_the_whitelist_is_refused() -> None:
    result = run_python("import os\nos.getcwd()\n", timeout_s=30, memory_mb=512)
    assert not result.ok
    assert "白名单" in (result.error or "")


def test_open_is_not_a_builtin_inside_the_sandbox() -> None:
    result = run_python("open('escape.txt', 'w').write('x')\n", timeout_s=30, memory_mb=512)
    assert not result.ok
    assert "open" in (result.error or "")


def test_script_without_a_figure_fails() -> None:
    result = run_python("value = 1 + 1\n", timeout_s=30, memory_mb=512)
    assert not result.ok
    assert "没有留下" in (result.error or "")


def test_wall_clock_limit() -> None:
    result = run_python("while True:\n    pass\n", timeout_s=1.0, memory_mb=512)
    assert not result.ok
    assert "秒" in (result.error or "")


def test_memory_limit() -> None:
    script = (
        "payload = bytearray(300 * 1024 * 1024)\n"
        "for index in range(0, len(payload), 4096):\n"
        "    payload[index] = 1\n"
        "while True:\n"
        "    pass\n"
    )
    result = run_python(script, timeout_s=30, memory_mb=256)
    assert not result.ok
    assert "内存" in (result.error or "") or "MemoryError" in (result.error or "")


def test_sandbox_env_drops_parent_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANDBOX_SECRET", "top-secret")
    env = sandbox_env(tmp_path)
    assert "SANDBOX_SECRET" not in env
    assert env["HOME"] == str(tmp_path)
    assert env["TEMP"] == str(tmp_path / "tmp")


def test_parent_secrets_are_not_visible_inside_the_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANDBOX_SECRET", "top-secret")
    script = (
        "from pandas.compat import os as pdos\n"
        "raise RuntimeError(pdos.environ.get('SANDBOX_SECRET', 'absent'))\n"
    )
    result = run_python(script, timeout_s=30, memory_mb=512)
    assert not result.ok
    assert "top-secret" not in (result.error or "")
    assert "absent" in (result.error or "")


def test_sandbox_is_deterministic() -> None:
    script = (
        "import random\n"
        "import numpy as np\n"
        "import matplotlib.pyplot as plt\n"
        "fig, ax = plt.subplots()\n"
        "ax.plot([random.random(), np.random.rand()])\n"
    )
    first = run_python(script, timeout_s=30, memory_mb=512)
    second = run_python(script, timeout_s=30, memory_mb=512)
    assert first.ok and second.ok
    assert first.image == second.image
