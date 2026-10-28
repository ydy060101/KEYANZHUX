"""Shape and safety checks for generated figure scripts (T7.2).

A script is checked before it reaches a renderer, and the same check supplies
the error text for the auto-fix prompt. The Python check is the H09 library
whitelist enforced in the parent; `sandbox/runner.py` enforces it again at
import time.
"""

from __future__ import annotations

import ast
import re
from typing import Literal

FigureKind = Literal["mermaid", "graphviz", "tikz", "matplotlib"]

MAX_SCRIPT_CHARS = 20_000
MAX_MERMAID_LINES = 300

_PYTHON_IMPORTS = frozenset(
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
_PYTHON_CALLS = frozenset(
    {"open", "eval", "exec", "compile", "__import__", "input", "breakpoint", "exit", "quit"}
)
_PYTHON_ATTRS = frozenset(
    {
        "system",
        "popen",
        "spawn",
        "spawnl",
        "spawnv",
        "fork",
        "execv",
        "execl",
        "remove",
        "unlink",
        "rmdir",
        "rmtree",
        "chdir",
        "getenv",
        "putenv",
        "kill",
        "terminate",
        "savefig",
        "imsave",
        "savetxt",
        "save",
        "savez",
        "savez_compressed",
        "read_csv",
        "read_excel",
        "read_json",
        "read_pickle",
        "read_parquet",
        "read_feather",
        "read_hdf",
        "read_sql",
        "read_table",
        "read_fwf",
        "read_clipboard",
        "read_html",
        "read_xml",
        "read_orc",
        "read_sas",
        "read_spss",
        "read_stata",
        "to_csv",
        "to_excel",
        "to_json",
        "to_pickle",
        "to_parquet",
        "to_feather",
        "to_hdf",
        "to_sql",
        "to_stata",
        "to_clipboard",
        "load",
        "loadtxt",
        "genfromtxt",
        "fromfile",
        "imread",
    }
)
_MERMAID_STARTS = (
    "flowchart",
    "graph",
    "sequencediagram",
    "classdiagram",
    "statediagram",
    "erdiagram",
    "journey",
    "gantt",
    "pie",
    "quadrantchart",
    "requirementdiagram",
    "gitgraph",
    "mindmap",
    "timeline",
    "sankey",
    "xychart",
    "block-beta",
    "packet-beta",
    "architecture-beta",
    "c4",
)
_TIKZ_BAD = re.compile(
    r"\\(?:write18|input|include|openout|read|special|directlua|immediate\s*\\write)\b"
    r"|\\usepackage\s*\{\s*(?:shellesc|minted)\s*\}",
    re.IGNORECASE,
)
_GRAPHVIZ_BAD = re.compile(r"\b(?:image|href|URL|shapefile|fontpath)\s*=", re.IGNORECASE)
_FENCE_HEAD = re.compile(r"^```[\w+-]*\s*")


def _balanced(text: str) -> bool:
    pairs = {")": "(", "]": "[", "}": "{"}
    stack: list[str] = []
    quote: str | None = None
    escaped = False
    for char in text:
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in ('"', "'"):
            quote = char
        elif char in "([{":
            stack.append(char)
        elif char in ")]}" and (not stack or stack.pop() != pairs[char]):
            return False
    return not stack and quote is None


def clean_script(kind: FigureKind, text: str) -> str:
    value = text.strip()
    value = _FENCE_HEAD.sub("", value)
    value = re.sub(r"\s*```$", "", value).strip()
    if kind == "mermaid":
        lines = value.splitlines()
        for index, line in enumerate(lines):
            word = line.strip().split(" ", 1)[0].casefold()
            if any(word.startswith(prefix) for prefix in _MERMAID_STARTS):
                value = "\n".join(lines[index:]).strip()
                break
    elif kind == "graphviz":
        match = re.search(r"\b(?:di)?graph\b", value, re.IGNORECASE)
        if match:
            value = value[match.start() :].strip()
    elif kind == "tikz":
        value = ensure_tikz_document(value)
    return value


def ensure_tikz_document(text: str) -> str:
    if "\\documentclass" in text:
        return text
    body = text
    if "\\begin{document}" not in body:
        body = "\\begin{document}\n" + body + "\n\\end{document}\n"
    return "\\documentclass[tikz,border=4pt]{standalone}\n" + body


def validate_mermaid(script: str) -> str | None:
    if not script.strip():
        return "Mermaid 脚本为空"
    if len(script) > MAX_SCRIPT_CHARS:
        return f"Mermaid 脚本超过 {MAX_SCRIPT_CHARS} 字符"
    if len(script.splitlines()) > MAX_MERMAID_LINES:
        return f"Mermaid 脚本超过 {MAX_MERMAID_LINES} 行"
    lowered = script.casefold()
    if "<script" in lowered or "javascript:" in lowered:
        return "Mermaid 脚本包含可执行内容"
    if re.search(r"^\s*click\s", script, re.IGNORECASE | re.MULTILINE):
        return "Mermaid 脚本包含 click 交互指令"
    first = script.splitlines()[0].strip().split(" ", 1)[0].casefold()
    if not any(first.startswith(prefix) for prefix in _MERMAID_STARTS):
        return "Mermaid 脚本必须以 flowchart/graph/sequenceDiagram 等图表类型开头"
    if not _balanced(script):
        return "Mermaid 脚本的括号或引号不匹配"
    return None


def validate_graphviz(script: str) -> str | None:
    if not script.strip():
        return "Graphviz 脚本为空"
    if len(script) > MAX_SCRIPT_CHARS:
        return f"Graphviz 脚本超过 {MAX_SCRIPT_CHARS} 字符"
    if not re.search(r"\b(?:di)?graph\b", script, re.IGNORECASE):
        return "DOT 脚本缺少 graph/digraph 声明"
    if not _balanced(script):
        return "DOT 脚本的括号或引号不匹配"
    if _GRAPHVIZ_BAD.search(script):
        return "DOT 脚本不得引用外部图片、文件或 URL"
    return None


def validate_tikz(script: str) -> str | None:
    if not script.strip():
        return "TikZ 脚本为空"
    if len(script) > MAX_SCRIPT_CHARS:
        return f"TikZ 脚本超过 {MAX_SCRIPT_CHARS} 字符"
    if "\\begin{document}" not in script or "\\end{document}" not in script:
        return "TikZ 脚本缺少完整的 document 环境"
    if "tikzpicture" not in script:
        return "TikZ 脚本缺少 tikzpicture 环境"
    if _TIKZ_BAD.search(script):
        return "TikZ 脚本包含文件读写或 shell 命令"
    return None


def validate_python(script: str) -> str | None:
    if not script.strip():
        return "Python 脚本为空"
    if len(script) > MAX_SCRIPT_CHARS:
        return f"Python 脚本超过 {MAX_SCRIPT_CHARS} 字符"
    try:
        tree = ast.parse(script)
    except SyntaxError as exc:
        line = exc.lineno or "?"
        return f"Python 语法错误（第 {line} 行）：{exc.msg}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in _PYTHON_IMPORTS:
                    return f"不允许导入模块 {root}"
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if node.level or root not in _PYTHON_IMPORTS:
                return f"不允许导入模块 {root or '相对导入'}"
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _PYTHON_CALLS:
                return f"不允许调用 {node.func.id}()"
            if isinstance(node.func, ast.Attribute) and node.func.attr in _PYTHON_ATTRS:
                return f"不允许调用 .{node.func.attr}()"
        elif isinstance(node, ast.Attribute) and node.attr in _PYTHON_ATTRS:
            return f"不允许使用属性 .{node.attr}"
    return None


def validate_script(kind: FigureKind, script: str) -> str | None:
    if kind == "mermaid":
        return validate_mermaid(script)
    if kind == "graphviz":
        return validate_graphviz(script)
    if kind == "tikz":
        return validate_tikz(script)
    return validate_python(script)


__all__ = [
    "FigureKind",
    "MAX_SCRIPT_CHARS",
    "clean_script",
    "ensure_tikz_document",
    "validate_graphviz",
    "validate_mermaid",
    "validate_python",
    "validate_script",
    "validate_tikz",
]
