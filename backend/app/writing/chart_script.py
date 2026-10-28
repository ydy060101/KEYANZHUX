"""Reproducible matplotlib script for a chart (T7.3).

`ChartResult.script` lets a reader regenerate the PNG from their own CSV. The
script is returned, not executed here; `figures/run` belongs to T7.2.
"""

from __future__ import annotations

from .chart import ChartKind

_HEADER = (
    "import pandas as pd\n"
    "import matplotlib.pyplot as plt\n\n"
    "df = pd.read_csv('dataset.csv')  # point this at your CSV\n"
    "x, ys = {x!r}, {ys!r}\n"
)

_TABLE = """

print(df[[x, *ys]].head(20).to_string(index=False))
"""

_LINE = """

fig, ax = plt.subplots(figsize=(7.2, 4.4))
for y in ys:
    ax.plot(df[x].astype(str), df[y], marker='o', label=y)
ax.set_xlabel(x)
ax.set_ylabel('value')
ax.grid(axis='y', alpha=0.3)
if len(ys) > 1:
    ax.legend(frameon=False)
fig.tight_layout()
fig.savefig('figure.png', dpi=150)
"""

_BAR = """

fig, ax = plt.subplots(figsize=(7.2, 4.4))
df.plot.bar(x=x, y=ys, ax=ax)
ax.set_ylabel('value')
ax.grid(axis='y', alpha=0.3)
fig.tight_layout()
fig.savefig('figure.png', dpi=150)
"""

_RADAR = """

fig, ax = plt.subplots(figsize=(6.4, 5.2), subplot_kw={'projection': 'polar'})
for y in ys:
    values = df[y].astype(float).tolist()
    lo, hi = min(values), max(values)
    norm = [0.5] * len(values) if hi == lo else [(v - lo) / (hi - lo) for v in values]
    ax.plot(angles, norm + norm[:1], marker='o', label=y)
ax.set_xticks(angles[:-1])
ax.set_xticklabels(labels)
ax.set_ylim(0, 1)
ax.legend(frameon=False)
fig.tight_layout()
fig.savefig('figure.png', dpi=150)
"""

_RADAR_3D = """

fig = plt.figure(figsize=(7.2, 5.2))
ax = fig.add_subplot(projection='3d')
for depth, y in enumerate(ys):
    values = df[y].astype(float).tolist()
    lo, hi = min(values), max(values)
    norm = [0.5] * len(values) if hi == lo else [(v - lo) / (hi - lo) for v in values]
    closed = norm + norm[:1]
    ax.plot([v * math.cos(a) for v, a in zip(closed, angles)],
            [v * math.sin(a) for v, a in zip(closed, angles)],
            [depth] * len(closed), linewidth=1.8, label=y)
ax.set_zticks(list(range(len(ys))))
ax.set_zticklabels(ys)
ax.set_xlim(-1.05, 1.05)
ax.set_ylim(-1.05, 1.05)
fig.tight_layout()
fig.savefig('figure.png', dpi=150)
"""

_ANGLES = (
    "\nimport math\n"
    "labels = [str(v) for v in df[x]]\n"
    "angles = [2 * math.pi * i / len(labels) for i in range(len(labels))]\n"
    "angles.append(angles[0])\n"
)


def script_for(x: str, ys: list[str], kind: ChartKind) -> str:
    """The same operations the server ran, in a standalone file."""
    header = _HEADER.format(x=x, ys=ys)
    if kind == "table":
        return header + _TABLE
    if kind == "line":
        return header + _LINE
    if kind == "bar":
        return header + _BAR
    if kind == "radar":
        return header + _ANGLES + _RADAR
    return header + _ANGLES + _RADAR_3D


__all__ = ["script_for"]
