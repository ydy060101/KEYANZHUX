"""Render a generated figure script (T7.2).

Matplotlib runs in the H09 sandbox. Graphviz uses the real `dot` binary when it
is installed, otherwise a clearly labelled built-in preview. TikZ compiles only
when pdflatex/tectonic exists; otherwise the source is returned untouched with
a note, as the architecture requires. Mermaid is rendered by the frontend.
"""

from __future__ import annotations

import base64
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..config import get_settings
from ..sandbox import run_python, sandbox_env
from ..sandbox.process import run_limited
from .dot_preview import render_dot_preview
from .validate import FigureKind, validate_script

MAX_RENDERED_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class RenderOutcome:
    rendered: str | None
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    renderer: str = ""


def _data_url(mime: str, payload: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(payload).decode('ascii')}"


def _too_large(payload: bytes) -> str | None:
    return "渲染结果超过 8 MB，请简化图" if len(payload) > MAX_RENDERED_BYTES else None


def _env(work: Path) -> dict[str, str]:
    return sandbox_env(
        work,
        {
            "MPLBACKEND": "Agg",
            "MPLCONFIGDIR": str(work / "mpl"),
            "TEXMFVAR": str(work / "texmf"),
            "TEXMFCACHE": str(work / "texmf"),
        },
    )


def render_matplotlib(script: str) -> RenderOutcome:
    settings = get_settings()
    result = run_python(script, timeout_s=settings.sandbox_timeout_s, memory_mb=settings.sandbox_memory_mb)
    if not result.ok or result.image is None:
        return RenderOutcome(None, [result.error or "脚本运行失败"], [], "matplotlib")
    oversized = _too_large(result.image)
    if oversized:
        return RenderOutcome(None, [oversized], [], "matplotlib")
    return RenderOutcome(_data_url("image/png", result.image), [], [], "matplotlib")


def render_graphviz(script: str) -> RenderOutcome:
    dot = shutil.which("dot")
    if dot is None:
        try:
            payload = render_dot_preview(script)
        except ValueError as exc:
            return RenderOutcome(None, [f"DOT 预览失败：{exc}"], [], "builtin")
        oversized = _too_large(payload)
        if oversized:
            return RenderOutcome(None, [oversized], [], "builtin")
        return RenderOutcome(
            _data_url("image/png", payload),
            [],
            ["未检测到 Graphviz dot，已使用内置布局预览；安装 Graphviz 后可得官方布局"],
            "builtin",
        )
    with tempfile.TemporaryDirectory(prefix="figure-dot-") as raw:
        work = Path(raw)
        (work / "mpl").mkdir()
        source = work / "figure.dot"
        output = work / "figure.svg"
        source.write_text(script, "utf-8")
        result = run_limited(
            [dot, "-Tsvg", "figure.dot", "-o", "figure.svg"],
            cwd=work,
            timeout_s=get_settings().sandbox_timeout_s,
            memory_mb=get_settings().sandbox_memory_mb,
            env=_env(work),
        )
        if result.reason == "timeout":
            return RenderOutcome(None, ["Graphviz 渲染超时，已终止"], [], "graphviz")
        if result.reason == "memory":
            return RenderOutcome(None, ["Graphviz 渲染超过内存上限，已终止"], [], "graphviz")
        if not output.is_file() or output.stat().st_size == 0:
            detail = (result.stderr or result.stdout).strip()[:1200]
            return RenderOutcome(None, [f"Graphviz 渲染失败：{detail or '未生成 SVG'}"], [], "graphviz")
        payload = output.read_bytes()
        oversized = _too_large(payload)
        if oversized:
            return RenderOutcome(None, [oversized], [], "graphviz")
        return RenderOutcome(_data_url("image/svg+xml", payload), [], [], "graphviz")


def _latex_command(engine: str, path: str) -> list[str]:
    if engine == "tectonic":
        return [path, "--outdir", ".", "figure.tex"]
    return [path, "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", "figure.tex"]


def render_tikz(script: str) -> RenderOutcome:
    engine = next(((name, shutil.which(name)) for name in ("pdflatex", "tectonic") if shutil.which(name)), None)
    if engine is None:
        return RenderOutcome(
            None,
            [],
            ["未检测到 LaTeX 环境（pdflatex/tectonic），仅返回 TikZ 源码"],
            "unavailable",
        )
    name, path = engine
    assert path is not None
    with tempfile.TemporaryDirectory(prefix="figure-tikz-") as raw:
        work = Path(raw)
        (work / "mpl").mkdir()
        (work / "figure.tex").write_text(script, "utf-8")
        result = run_limited(
            _latex_command(name, path),
            cwd=work,
            timeout_s=get_settings().sandbox_timeout_s,
            memory_mb=get_settings().sandbox_memory_mb,
            env=_env(work),
        )
        if result.reason == "timeout":
            return RenderOutcome(None, ["LaTeX 编译超时，已终止"], [], name)
        if result.reason == "memory":
            return RenderOutcome(None, ["LaTeX 编译超过内存上限，已终止"], [], name)
        pdf = work / "figure.pdf"
        if not pdf.is_file():
            detail = (result.stderr or result.stdout).strip()[-1200:]
            return RenderOutcome(None, [f"LaTeX 编译失败：{detail or '未生成 PDF'}"], [], name)
        import fitz

        document = fitz.open(pdf)
        try:
            if document.page_count == 0:
                return RenderOutcome(None, ["LaTeX 生成了空 PDF"], [], name)
            pixmap = document[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            payload = pixmap.tobytes("png")
        finally:
            document.close()
        oversized = _too_large(payload)
        if oversized:
            return RenderOutcome(None, [oversized], [], name)
        return RenderOutcome(_data_url("image/png", payload), [], [], name)


def render_mermaid(_script: str) -> RenderOutcome:
    return RenderOutcome(
        None,
        [],
        ["Mermaid 语法已通过后端检查，图形由前端 mermaid 渲染"],
        "frontend",
    )


def render_figure(kind: FigureKind, script: str) -> RenderOutcome:
    invalid = validate_script(kind, script)
    if invalid is not None:
        return RenderOutcome(None, [invalid], [], kind)
    if kind == "matplotlib":
        return render_matplotlib(script)
    if kind == "graphviz":
        return render_graphviz(script)
    if kind == "tikz":
        return render_tikz(script)
    return render_mermaid(script)


__all__ = ["RenderOutcome", "render_figure"]
