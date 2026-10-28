"""Chart statistics and server-side PNG rendering (T7.3).

The numbers in `stats` are the only evidence a caption may cite; `caption.py`
checks the model's text against them. Rendering is done with matplotlib's Agg
backend because `ChartResult.image_url` must hold a ready image (the browser
still draws the interactive ECharts view from the same stats).
"""

from __future__ import annotations

import base64
import math
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from ..config import get_settings
from ..errors import InvalidRequest

ChartKind = Literal["table", "line", "bar", "radar", "radar3d"]
RADAR_KINDS = ("radar", "radar3d")
MAX_SERIES = 6
MAX_TABLE_ROWS = 20
MIN_RADAR_CATEGORIES = 3
MAX_RADAR_CATEGORIES = 12
MAX_TICKS = 12
FIGURE_DPI = 150

_FONTS = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]


def _scalar(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float):
        return int(value) if value.is_integer() else round(value, 4)
    return value


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(float(value), digits)


def _slope(xs: list[float], ys: list[float]) -> float | None:
    count = len(xs)
    if count < 2:
        return None
    x_mean = sum(xs) / count
    y_mean = sum(ys) / count
    denominator = sum((value - x_mean) ** 2 for value in xs)
    if denominator == 0:
        return None
    return sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=True)) / denominator


def prepare(frame: pd.DataFrame, x: str, ys: list[str], kind: ChartKind) -> pd.DataFrame:
    """Validate the selection and coerce y to numbers for non-table charts."""
    missing = [column for column in [x, *ys] if column not in frame.columns]
    if missing:
        raise InvalidRequest("数据集中不存在所选列", detail={"columns": missing})
    data = frame[[x, *ys]].copy()
    data = data.dropna(subset=[x])
    if kind != "table":
        for name in ys:
            data[name] = pd.to_numeric(data[name], errors="coerce")
        how = "any" if kind in RADAR_KINDS else "all"
        data = data.dropna(subset=ys, how=how)
    if data.empty:
        raise InvalidRequest("所选列没有可用于绘图的数据")
    if kind in RADAR_KINDS and not MIN_RADAR_CATEGORIES <= len(data) <= MAX_RADAR_CATEGORIES:
        raise InvalidRequest(
            f"雷达图需要 {MIN_RADAR_CATEGORIES}–{MAX_RADAR_CATEGORIES} 个类别",
            detail={"categories": int(len(data))},
        )
    return data


def _series_stats(data: pd.DataFrame, x: str, name: str) -> dict[str, Any]:
    raw = data[name]
    numeric = pd.to_numeric(raw, errors="coerce")
    valid = numeric.dropna()
    if valid.empty:
        return {"numeric": False, "n": int(raw.notna().sum())}

    first = float(valid.iloc[0])
    last = float(valid.iloc[-1])
    peak_position = valid.idxmax()
    positions = pd.to_numeric(data.loc[valid.index, x], errors="coerce")
    if len(valid) >= 2 and bool(positions.notna().all()) and int(positions.nunique()) > 1:
        xs = [float(value) for value in positions.tolist()]
        basis = "x"
    else:
        xs = [float(index) for index in range(len(valid))]
        basis = "index"
    slope = _slope(xs, [float(value) for value in valid.tolist()])
    change = (last - first) / abs(first) if first != 0 else None
    return {
        "numeric": True,
        "n": int(len(valid)),
        "dropped": int(raw.notna().sum()) - int(len(valid)),
        "min": _scalar(valid.min()),
        "max": _scalar(valid.max()),
        "mean": _scalar(valid.mean()),
        "start": _scalar(first),
        "end": _scalar(last),
        "change_rate": _round(change),
        "slope": _round(slope, 6),
        "slope_basis": basis,
        "peak_x": _scalar(data.loc[peak_position, x]),
        "peak_value": _scalar(valid.loc[peak_position]),
    }


def compute_stats(data: pd.DataFrame, x: str, ys: list[str], kind: ChartKind) -> dict[str, Any]:
    x_values = data[x]
    x_numeric = pd.to_numeric(x_values, errors="coerce")
    x_stats: dict[str, Any] = {
        "name": x,
        "first": _scalar(x_values.iloc[0]),
        "last": _scalar(x_values.iloc[-1]),
        "unique": int(x_values.nunique(dropna=True)),
    }
    if bool(x_numeric.notna().all()):
        x_stats["min"] = _scalar(x_numeric.min())
        x_stats["max"] = _scalar(x_numeric.max())
    stats: dict[str, Any] = {
        "type": kind,
        "rows": int(len(data)),
        "series_count": len(ys),
        "x": x_stats,
        "series": {name: _series_stats(data, x, name) for name in ys},
    }
    if kind in RADAR_KINDS:
        stats["normalized"] = "min-max per series"
    return stats


def _pyplot() -> Any:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _label(value: Any) -> str:
    scalar = _scalar(value)
    return "—" if scalar is None else str(scalar)


def _ticks(positions: list[int], labels: list[str]) -> tuple[list[int], list[str], int]:
    if len(positions) <= MAX_TICKS:
        rotation = 30 if any(len(label) > 8 for label in labels) else 0
        return positions, labels, rotation
    step = math.ceil(len(positions) / MAX_TICKS)
    return positions[::step], labels[::step], 30


def _draw_table(plt: Any, data: pd.DataFrame, x: str, ys: list[str]) -> Any:
    shown = data.head(MAX_TABLE_ROWS)
    columns = [x, *ys]
    rows = [[_label(value) for value in record] for record in shown[columns].itertuples(index=False, name=None)]
    height = 0.6 + 0.32 * len(rows)
    fig = plt.figure(figsize=(7.4, min(height, 8.0)))
    ax = fig.add_subplot(111)
    ax.axis("off")
    table = ax.table(cellText=rows, colLabels=columns, loc="center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.35)
    return fig


def _draw_series(plt: Any, data: pd.DataFrame, x: str, ys: list[str], kind: ChartKind) -> Any:
    labels = [_label(value) for value in data[x].tolist()]
    positions = list(range(len(labels)))
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    if kind == "bar":
        width = 0.8 / len(ys)
        for offset, name in enumerate(ys):
            shifted = [position + offset * width - 0.4 + width / 2 for position in positions]
            ax.bar(shifted, data[name].tolist(), width=width, label=name)
    else:
        marker = "o" if len(labels) <= MAX_TICKS else None
        for name in ys:
            ax.plot(positions, data[name].tolist(), marker=marker, linewidth=1.6, label=name)
    ticks, tick_labels, rotation = _ticks(positions, labels)
    ax.set_xticks(ticks)
    ax.set_xticklabels(tick_labels, rotation=rotation, ha="right" if rotation else "center")
    ax.set_xlabel(x)
    ax.set_ylabel(ys[0] if len(ys) == 1 else "value")
    ax.grid(axis="y", alpha=0.3)
    if len(ys) > 1:
        ax.legend(frameon=False)
    fig.tight_layout()
    return fig


def _normalize(data: pd.DataFrame, ys: list[str]) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for name in ys:
        values = [float(value) for value in data[name].tolist()]
        low, high = min(values), max(values)
        out[name] = [0.5] * len(values) if high == low else [(value - low) / (high - low) for value in values]
    return out


def _draw_radar(plt: Any, data: pd.DataFrame, x: str, ys: list[str], *, three_d: bool) -> Any:
    categories = len(data)
    if not MIN_RADAR_CATEGORIES <= categories <= MAX_RADAR_CATEGORIES:
        raise InvalidRequest(
            f"雷达图需要 {MIN_RADAR_CATEGORIES}–{MAX_RADAR_CATEGORIES} 个类别",
            detail={"categories": categories},
        )
    labels = [_label(value) for value in data[x].tolist()]
    angles = [2 * math.pi * index / categories for index in range(categories)]
    closed = [*angles, angles[0]]
    series = _normalize(data, ys)
    if three_d:
        fig = plt.figure(figsize=(7.2, 5.2))
        ax = fig.add_subplot(projection="3d")
        for depth, name in enumerate(ys):
            values = [*series[name], series[name][0]]
            ax.plot(
                [value * math.cos(angle) for value, angle in zip(values, closed, strict=True)],
                [value * math.sin(angle) for value, angle in zip(values, closed, strict=True)],
                [depth] * len(values),
                linewidth=1.8,
                label=name,
            )
        ax.set_zticks(list(range(len(ys))))
        ax.set_zticklabels(ys)
        ax.set_xlim(-1.05, 1.05)
        ax.set_ylim(-1.05, 1.05)
        ax.set_zlim(-0.2, max(len(ys) - 1, 0) + 0.2)
    else:
        fig, ax = plt.subplots(figsize=(6.4, 5.2), subplot_kw={"projection": "polar"})
        for name in ys:
            values = [*series[name], series[name][0]]
            ax.plot(closed, values, marker="o", linewidth=1.6, label=name)
        ax.set_xticks(angles)
        ax.set_xticklabels(labels)
        ax.set_ylim(0, 1)
        ax.legend(frameon=False, loc="upper right", bbox_to_anchor=(1.25, 1.1))
    fig.tight_layout()
    return fig


def render_chart(data: pd.DataFrame, x: str, ys: list[str], kind: ChartKind, path: Path) -> None:
    plt = _pyplot()
    path.parent.mkdir(parents=True, exist_ok=True)
    settings = {"font.sans-serif": _FONTS, "axes.unicode_minus": False, "figure.facecolor": "white"}
    with plt.rc_context(settings):
        if kind == "table":
            fig = _draw_table(plt, data, x, ys)
        elif kind in RADAR_KINDS:
            fig = _draw_radar(plt, data, x, ys, three_d=kind == "radar3d")
        else:
            fig = _draw_series(plt, data, x, ys, kind)
        fig.savefig(path, format="png", dpi=FIGURE_DPI, bbox_inches="tight", facecolor="white")
        plt.close(fig)


def figure_path(figure_id: str) -> Path:
    folder = get_settings().data_dir / "figures"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{figure_id}.png"


def png_data_url(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


__all__ = [
    "MAX_SERIES",
    "RADAR_KINDS",
    "ChartKind",
    "compute_stats",
    "figure_path",
    "png_data_url",
    "prepare",
    "render_chart",
]
