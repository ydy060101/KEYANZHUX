"""T7.2 acceptance: script validation, DOT preview, rendering and repair."""

from __future__ import annotations

import io
from collections.abc import AsyncIterator
from typing import Any

import matplotlib.image as mpimg
import pytest
from httpx import ASGITransport, AsyncClient

from app.figures import render as render_module
from app.figures import service as figure_service
from app.figures.dot_preview import parse_dot, render_dot_preview
from app.figures.render import render_figure
from app.figures.validate import (
    clean_script,
    validate_graphviz,
    validate_mermaid,
    validate_python,
    validate_tikz,
)
from app.llm.errors import LLMUnavailable

PLOT = """
import matplotlib.pyplot as plt

fig, ax = plt.subplots()
ax.plot([1, 2, 3], [1, 4, 9])
ax.set_title("repair")
"""

DOT = 'digraph G { rankdir=LR; A [label="Start"]; B [label="End"]; A -> B [label="yes"]; }'


class ScriptedGateway:
    def __init__(self, items: list[str | Exception]) -> None:
        self.items = list(items)
        self.calls = 0

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        schema: type[Any],
        *,
        tier: str = "fast",
        temperature: float = 0.0,
        cache_prefix: str | None = None,
    ) -> Any:
        item = self.items[min(self.calls, len(self.items) - 1)]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return schema(script=item)


def test_clean_script_strips_fences_and_completes_tikz() -> None:
    assert clean_script("mermaid", "```mermaid\nflowchart TD\n  A --> B\n```") == "flowchart TD\n  A --> B"
    tikz = clean_script("tikz", "\\begin{tikzpicture}\\draw (0,0)--(1,1);\\end{tikzpicture}")
    assert tikz.startswith("\\documentclass")
    assert "\\begin{document}" in tikz and "\\end{document}" in tikz
    assert validate_tikz(tikz) is None


def test_validators_accept_simple_scripts_and_reject_escapes() -> None:
    assert validate_mermaid("flowchart TD\n  A[开始] --> B[结束]") is None
    assert validate_mermaid("A --> B") is not None
    assert validate_mermaid("flowchart TD\n  A[开始 --> B") is not None
    assert validate_mermaid("flowchart TD\n  click A callback") is not None

    assert validate_graphviz(DOT) is None
    assert validate_graphviz("digraph G { A [image=\"secret.png\"]; }") is not None
    assert validate_graphviz("digraph G { A -> B ") is not None

    assert validate_python("import matplotlib.pyplot as plt\nfig, ax = plt.subplots()\n") is None
    assert "os" in (validate_python("import os\n") or "")
    assert "open" in (validate_python("open('x')") or "")
    assert "system" in (validate_python("import matplotlib\nmatplotlib.os.system('x')") or "")
    assert "语法" in (validate_python("def broken(:\n") or "")


def test_python_validator_rejects_file_io() -> None:
    scripts = (
        "import pandas as pd\ndf = pd.read_csv('data.csv')\n",
        "import matplotlib.pyplot as plt\nplt.savefig('x.png')\n",
        "import pandas as pd\ndf.to_csv('x.csv')\n",
        "import numpy as np\nnp.load('x.npy')\n",
    )
    for script in scripts:
        assert validate_python(script) is not None, script


def test_dot_parser_reads_nodes_labels_and_edges() -> None:
    graph = parse_dot(DOT)
    assert graph.nodes == ["A", "B"]
    assert graph.labels == {"A": "Start", "B": "End"}
    assert graph.edges == [("A", "B", "yes")]
    assert render_dot_preview(DOT).startswith(b"\x89PNG\r\n\x1a\n")


def test_dot_preview_is_bounded_and_draws_arrows() -> None:
    source = (
        'digraph G { rankdir=TB; A [label="Query"]; '
        'B [label="Naive RAG branch with a deliberately long label"]; '
        'C [label="Another branch"]; A -> B; A -> C; }'
    )
    png = render_dot_preview(source)
    image = mpimg.imread(io.BytesIO(png))
    height, width = image.shape[:2]
    assert width <= 2000
    assert height <= 2000
    band = image[int(height * 0.3) : int(height * 0.55)]
    dark = band[..., :3].mean(axis=2) < 0.6
    assert dark.sum() > 100


def test_mermaid_is_delegated_to_the_frontend() -> None:
    outcome = render_figure("mermaid", "flowchart TD\n  A --> B")
    assert outcome.rendered is None
    assert outcome.errors == []
    assert outcome.renderer == "frontend"
    assert any("前端" in note for note in outcome.notes)


def test_graphviz_uses_the_builtin_preview_without_dot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(render_module.shutil, "which", lambda name: None)
    outcome = render_figure("graphviz", DOT)
    assert outcome.errors == []
    assert outcome.rendered is not None and outcome.rendered.startswith("data:image/png;base64,")
    assert outcome.renderer == "builtin"
    assert any("内置布局" in note for note in outcome.notes)


def test_tikz_without_latex_degrades_with_a_note(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(render_module.shutil, "which", lambda name: None)
    script = clean_script("tikz", "\\begin{tikzpicture}\\draw (0,0)--(1,1);\\end{tikzpicture}")
    outcome = render_figure("tikz", script)
    assert outcome.rendered is None
    assert outcome.errors == []
    assert outcome.renderer == "unavailable"
    assert any("未检测到 LaTeX" in note for note in outcome.notes)


async def test_generate_repairs_once(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = ScriptedGateway(["import os\n", PLOT])
    monkeypatch.setattr(figure_service, "get_gateway", lambda: fake)
    payload = await figure_service.generate_figure("matplotlib", "a line")
    assert fake.calls == 2
    assert payload["attempts"] == 1
    assert payload["errors"] == []
    assert payload["rendered"].startswith("data:image/png;base64,")
    assert any("修复 1 次" in note for note in payload["notes"])


async def test_generate_stops_when_the_fix_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = ScriptedGateway(["import os\n"])
    monkeypatch.setattr(figure_service, "get_gateway", lambda: fake)
    payload = await figure_service.generate_figure("matplotlib", "a line")
    assert fake.calls == 2
    assert payload["attempts"] == 0
    assert payload["errors"]
    assert any("未修改" in note for note in payload["notes"])


async def test_generate_gives_up_after_three_fixes(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = ScriptedGateway(["import os\n", "import os  # 1\n", "import os  # 2\n", "import os  # 3\n"])
    monkeypatch.setattr(figure_service, "get_gateway", lambda: fake)
    payload = await figure_service.generate_figure("matplotlib", "a line")
    assert fake.calls == 4
    assert payload["attempts"] == 3
    assert payload["errors"]
    assert any("已自动修复 3 次" in note for note in payload["notes"])


async def test_generate_propagates_an_initial_llm_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = ScriptedGateway([LLMUnavailable("down")])
    monkeypatch.setattr(figure_service, "get_gateway", lambda: fake)
    with pytest.raises(LLMUnavailable):
        await figure_service.generate_figure("mermaid", "a flow")


async def test_generate_keeps_the_script_when_a_repair_call_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = ScriptedGateway(["import os\n", LLMUnavailable("down")])
    monkeypatch.setattr(figure_service, "get_gateway", lambda: fake)
    payload = await figure_service.generate_figure("matplotlib", "a line")
    assert payload["script"] == "import os"
    assert payload["errors"]
    assert any("中断" in note for note in payload["notes"])


@pytest.fixture
async def client(session: Any) -> AsyncIterator[AsyncClient]:
    from app.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_run_endpoint_returns_a_png(client: AsyncClient) -> None:
    response = await client.post("/api/v1/figures/run", json={"kind": "matplotlib", "script": PLOT})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rendered"].startswith("data:image/png;base64,")
    assert body["errors"] == []
    assert body["renderer"] == "matplotlib"


async def test_run_endpoint_returns_a_structured_script_error(client: AsyncClient) -> None:
    response = await client.post("/api/v1/figures/run", json={"kind": "matplotlib", "script": "import os\n"})
    assert response.status_code == 200
    body = response.json()
    assert body["rendered"] is None
    assert body["errors"] and "os" in body["errors"][0]


async def test_run_and_generate_reject_blank_input(client: AsyncClient) -> None:
    blank_script = await client.post("/api/v1/figures/run", json={"kind": "mermaid", "script": "   "})
    assert blank_script.status_code == 400
    blank_description = await client.post(
        "/api/v1/figures/generate", json={"kind": "mermaid", "description": "   "}
    )
    assert blank_description.status_code == 400


async def test_generate_maps_llm_failure_to_502(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.api.figures as figures_api

    async def fail(kind: str, description: str) -> dict[str, Any]:
        raise LLMUnavailable("down")

    monkeypatch.setattr(figures_api, "generate_figure", fail)
    response = await client.post(
        "/api/v1/figures/generate", json={"kind": "mermaid", "description": "a flow"}
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "llm_unavailable"
