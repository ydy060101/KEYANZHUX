"""Built-in DOT preview used when Graphviz's `dot` is unavailable (T7.2).

This is deliberately not a Graphviz reimplementation: it reads the simple DOT
subset the generator is told to emit (nodes, labels, directed edges, rankdir)
and lays it out with matplotlib. The response marks the result as a preview so
it is never presented as Graphviz's own layout.
"""

from __future__ import annotations

import io
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

MAX_NODES = 60
MAX_EDGES = 120

_ATTR = re.compile(r"(\w+)\s*=\s*(\"((?:[^\"\\]|\\.)*)\"|[\w.#-]+)")
_SKIP_PREFIXES = ("rankdir", "nodesep", "ranksep", "splines", "bgcolor", "fontname", "fontsize", "label=")


@dataclass
class DotGraph:
    nodes: list[str] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)
    edges: list[tuple[str, str, str]] = field(default_factory=list)

    def add(self, node: str, label: str | None = None) -> None:
        if node not in self.labels:
            self.nodes.append(node)
            self.labels[node] = label or node
        elif label:
            self.labels[node] = label


def _strip_comments(text: str) -> str:
    out: list[str] = []
    index = 0
    quote = False
    while index < len(text):
        char = text[index]
        if quote:
            out.append(char)
            if char == "\\" and index + 1 < len(text):
                out.append(text[index + 1])
                index += 1
            elif char == '"':
                quote = False
            index += 1
            continue
        if char == '"':
            quote = True
            out.append(char)
            index += 1
        elif text.startswith("//", index) or (char == "#" and (index == 0 or text[index - 1] == "\n")):
            while index < len(text) and text[index] != "\n":
                index += 1
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            index = len(text) if end < 0 else end + 2
        else:
            out.append(char)
            index += 1
    return "".join(out)


def _body(text: str) -> str:
    match = re.search(r"\b(?:di)?graph\b", text, re.IGNORECASE)
    if match is None:
        raise ValueError("DOT 缺少 graph/digraph 声明")
    start = text.find("{", match.end())
    if start < 0:
        raise ValueError("DOT 缺少左花括号")
    depth = 0
    quote = False
    for index in range(start, len(text)):
        char = text[index]
        if quote:
            if char == '"' and text[index - 1] != "\\":
                quote = False
            continue
        if char == '"':
            quote = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : index]
    raise ValueError("DOT 的花括号不匹配")


def _statements(body: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    depth = 0
    quote = False
    for index, char in enumerate(body):
        if quote:
            current.append(char)
            if char == '"' and (index == 0 or body[index - 1] != "\\"):
                quote = False
            continue
        if char == '"':
            quote = True
            current.append(char)
        elif char in "[{(":
            depth += 1
            current.append(char)
        elif char in "]})":
            depth = max(depth - 1, 0)
            current.append(char)
        elif char in ";\n" and depth == 0:
            chunk = "".join(current).strip()
            if chunk:
                statements.append(chunk)
            current = []
        else:
            current.append(char)
    chunk = "".join(current).strip()
    if chunk:
        statements.append(chunk)
    return statements


def _node_id(raw: str) -> str:
    value = raw.strip()
    if value.startswith('"'):
        end = 1
        while end < len(value):
            if value[end] == '"' and value[end - 1] != "\\":
                break
            end += 1
        value = value[1:end]
    else:
        value = re.split(r"[\s\[]", value, maxsplit=1)[0]
    return value.split(":", 1)[0].strip()


def _attrs(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for match in _ATTR.finditer(raw):
        quoted = match.group(3)
        value = quoted if quoted is not None else match.group(2)
        out[match.group(1)] = value.replace('\\"', '"')
    return out


def _split_attrs(raw: str) -> tuple[str, str]:
    start = raw.find("[")
    end = raw.rfind("]")
    if start >= 0 and end > start:
        return raw[:start].strip(), raw[start + 1 : end]
    return raw.strip(), ""


def _chain(raw: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    quote = False
    index = 0
    while index < len(raw):
        char = raw[index]
        if quote:
            current.append(char)
            if char == '"' and raw[index - 1] != "\\":
                quote = False
            index += 1
            continue
        if char == '"':
            quote = True
            current.append(char)
            index += 1
        elif raw.startswith("->", index) or raw.startswith("--", index):
            parts.append("".join(current).strip())
            current = []
            index += 2
        else:
            current.append(char)
            index += 1
    parts.append("".join(current).strip())
    return [part for part in parts if part]


def parse_dot(source: str) -> DotGraph:
    graph = DotGraph()
    for statement in _statements(_body(_strip_comments(source))):
        stripped = statement.strip()
        if not stripped or stripped.startswith(("subgraph", "{")):
            continue
        if stripped.startswith(("node ", "edge ", "graph ")) or stripped.startswith(_SKIP_PREFIXES):
            continue
        if "{" in stripped:
            continue
        if "->" in stripped or "--" in stripped:
            chain_raw, attrs_raw = _split_attrs(stripped)
            parts = _chain(chain_raw)
            if len(parts) < 2:
                continue
            attrs = _attrs(attrs_raw)
            label = attrs.get("label", "")
            nodes = [_node_id(part) for part in parts]
            for node in nodes:
                if node:
                    graph.add(node)
            for left, right in zip(nodes, nodes[1:], strict=False):
                if left and right:
                    graph.edges.append((left, right, label))
            continue
        head, attrs_raw = _split_attrs(stripped)
        node = _node_id(head)
        if node:
            graph.add(node, _attrs(attrs_raw).get("label"))
    if len(graph.nodes) > MAX_NODES:
        raise ValueError(f"DOT 超过 {MAX_NODES} 个节点")
    if len(graph.edges) > MAX_EDGES:
        raise ValueError(f"DOT 超过 {MAX_EDGES} 条边")
    return graph


def _layers(graph: DotGraph) -> dict[str, int]:
    adjacency: dict[str, list[str]] = {node: [] for node in graph.nodes}
    indegree = dict.fromkeys(graph.nodes, 0)
    for left, right, _ in graph.edges:
        adjacency[left].append(right)
        indegree[right] = indegree.get(right, 0) + 1
    roots = [node for node in graph.nodes if indegree.get(node, 0) == 0] or graph.nodes[:1]
    depth = {node: 0 for node in roots}
    queue: deque[str] = deque(roots)
    while queue:
        node = queue.popleft()
        for child in adjacency.get(node, []):
            if child in depth:
                continue
            depth[child] = depth[node] + 1
            queue.append(child)
    return {node: depth.get(node, 0) for node in graph.nodes}


def _label_width(label: str) -> float:
    """Approximate a label's width in data units (9 pt, ~0.7 in per unit)."""
    units = sum(0.21 if ord(char) > 0x2E80 else 0.105 for char in label[:60])
    return max(1.8, units + 0.9)


def _row_offsets(labels: list[str], gap: float = 0.7) -> list[float]:
    widths = [_label_width(label) for label in labels]
    total = sum(widths) + gap * (len(widths) - 1)
    cursor = -total / 2
    offsets: list[float] = []
    for width in widths:
        offsets.append(cursor + width / 2)
        cursor += width + gap
    return offsets


def _layout(
    groups: dict[int, list[str]],
    labels: dict[str, str],
    vertical: bool,
) -> dict[str, tuple[float, float]]:
    positions: dict[str, tuple[float, float]] = {}
    if vertical:
        for layer in sorted(groups):
            nodes = groups[layer]
            offsets = _row_offsets([labels[node] for node in nodes])
            for node, offset in zip(nodes, offsets, strict=False):
                positions[node] = (offset, -layer * 2.2)
        return positions
    columns = {
        layer: max(_label_width(labels[node]) for node in nodes)
        for layer, nodes in groups.items()
    }
    x = 0.0
    for layer in sorted(groups):
        nodes = groups[layer]
        for row, node in enumerate(nodes):
            offset = row - (len(nodes) - 1) / 2
            positions[node] = (x, -offset * 1.25)
        x += columns[layer] + 1.2
    return positions


def _bounds(
    positions: dict[str, tuple[float, float]],
    labels: dict[str, str],
) -> tuple[float, float, float, float]:
    left = min(x - _label_width(labels[node]) / 2 for node, (x, _) in positions.items()) - 0.3
    right = max(x + _label_width(labels[node]) / 2 for node, (x, _) in positions.items()) + 0.3
    bottom = min(y for _, y in positions.values()) - 0.85
    top = max(y for _, y in positions.values()) + 0.85
    return left, right, bottom, top


def _figure_size(span_x: float, span_y: float) -> tuple[float, float]:
    """Keep the figure's aspect equal to the data's, so `set_aspect("equal")`
    cannot make `bbox_inches="tight"` expand the canvas by an order of
    magnitude (the first live TB graph came out 6566 x 17207 px)."""
    width = max(span_x * 0.7, 1e-3)
    height = max(span_y * 0.7, 1e-3)
    factor = max(1.0, 5.0 / width, 3.5 / height)
    return width * factor, height * factor


def _pyplot() -> Any:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def render_dot_preview(source: str) -> bytes:
    graph = parse_dot(source)
    if not graph.nodes:
        raise ValueError("DOT 中没有节点")
    depth = _layers(graph)
    groups: dict[int, list[str]] = defaultdict(list)
    for node in graph.nodes:
        groups[depth[node]].append(node)
    vertical = bool(re.search(r"rankdir\s*=\s*TB", source, re.IGNORECASE))
    positions = _layout(groups, graph.labels, vertical)
    left, right, bottom, top = _bounds(positions, graph.labels)
    width, height = _figure_size(right - left, top - bottom)

    plt = _pyplot()
    settings = {"font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"], "axes.unicode_minus": False}
    with plt.rc_context(settings):
        fig, ax = plt.subplots(figsize=(width, height))
        try:
            for source_id, target_id, label in graph.edges:
                start, end = positions[source_id], positions[target_id]
                ax.annotate(
                    "",
                    xy=end,
                    xytext=start,
                    arrowprops={"arrowstyle": "->", "color": "#475569", "lw": 1.1, "shrinkA": 18, "shrinkB": 18},
                )
                if label:
                    ax.text(
                        (start[0] + end[0]) / 2,
                        (start[1] + end[1]) / 2,
                        label[:40],
                        fontsize=8,
                        color="#475569",
                        ha="center",
                        va="center",
                        bbox={"boxstyle": "round,pad=0.2", "fc": "white", "ec": "none"},
                    )
            for node in graph.nodes:
                x, y = positions[node]
                ax.text(
                    x,
                    y,
                    graph.labels[node][:60],
                    fontsize=9,
                    ha="center",
                    va="center",
                    bbox={"boxstyle": "round,pad=0.45", "fc": "white", "ec": "#334155", "lw": 1.2},
                )
            ax.set_xlim(left, right)
            ax.set_ylim(bottom, top)
            ax.set_aspect("equal")
            ax.axis("off")
            buffer = io.BytesIO()
            fig.savefig(buffer, format="png", dpi=150, bbox_inches="tight", facecolor="white")
        finally:
            plt.close(fig)
    return buffer.getvalue()


__all__ = ["DotGraph", "parse_dot", "render_dot_preview"]
