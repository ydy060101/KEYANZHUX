"""T7.3 acceptance: CSV profiling, chart statistics and grounded captions.

Rendering is exercised for real (Agg writes a PNG); only the LLM is scripted.
The central guarantee is that a caption containing a number absent from the
computed stats is replaced by the deterministic template.
"""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient

from app.writing.caption import allowed_numbers, grounded, normalize_caption
from app.writing.chart import compute_stats, prepare
from app.writing.dataset import decode_csv

CSV_LINE = "year,accuracy,latency\n2020,70,120\n2021,80,100\n2022,90,80\n"


class FakeGateway:
    def __init__(self, caption: str, caption_zh: str = "图 1. 概览。") -> None:
        self.caption = caption
        self.caption_zh = caption_zh

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        schema: type[Any],
        *,
        tier: str = "fast",
        temperature: float = 0.0,
        cache_prefix: str | None = None,
    ) -> Any:
        return schema(caption=self.caption, caption_zh=self.caption_zh)


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    return tmp_path


@pytest.fixture
async def client(session: Any) -> AsyncIterator[AsyncClient]:
    from app.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _upload(client: AsyncClient, text: str, name: str = "data.csv") -> dict[str, Any]:
    response = await client.post("/api/v1/data/upload", files={"file": (name, text.encode("utf-8"), "text/csv")})
    assert response.status_code == 200, response.text
    return response.json()


def _fake(monkeypatch: pytest.MonkeyPatch, caption: str, caption_zh: str = "图 1. 概览。") -> None:
    import app.api.data as data_api

    monkeypatch.setattr(data_api, "get_gateway", lambda: FakeGateway(caption, caption_zh))


def test_decode_csv_accepts_gb18030() -> None:
    text = decode_csv("年份,值\n2020,1\n".encode("gb18030"))
    assert text.startswith("年份")


async def test_upload_returns_columns_and_json_safe_preview(client: AsyncClient, session: Any, data_dir: Path) -> None:
    from app.models.orm import Dataset

    text = "年份,准确率,备注\n2020,81.5,基线\n2021,,提升\n2022,88.25,最终\n"
    body = await _upload(client, text, name="实验 数据.csv")

    assert body["filename"] == "实验 数据.csv"
    assert body["row_count"] == 3
    assert [column["name"] for column in body["columns"]] == ["年份", "准确率", "备注"]
    assert body["columns"][1]["dtype"] == "float64"
    assert body["columns"][1]["missing_rate"] == 0.3333
    assert body["preview"][1]["准确率"] is None
    assert body["preview"][2]["准确率"] == 88.25

    row = await session.get(Dataset, body["id"])
    assert row is not None and isinstance(row.columns, list)
    assert (data_dir / row.path).is_file()


async def test_upload_rejects_non_csv(client: AsyncClient, data_dir: Path) -> None:
    response = await client.post("/api/v1/data/upload", files={"file": ("notes.txt", b"a,b\n1,2\n", "text/plain")})
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"


async def test_upload_rejects_an_empty_csv(client: AsyncClient, data_dir: Path) -> None:
    response = await client.post("/api/v1/data/upload", files={"file": ("empty.csv", b"", "text/csv")})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_stats_are_deterministic() -> None:
    frame = pd.DataFrame({"x": [1, 2, 3], "y": [2.0, 4.0, 8.0]})
    data = prepare(frame, "x", ["y"], "line")
    first = compute_stats(data, "x", ["y"], "line")
    second = compute_stats(data, "x", ["y"], "line")
    assert first == second
    assert first["series"]["y"] == {
        "numeric": True,
        "n": 3,
        "dropped": 0,
        "min": 2,
        "max": 8,
        "mean": 4.6667,
        "start": 2,
        "end": 8,
        "change_rate": 3.0,
        "slope": 3.0,
        "slope_basis": "x",
        "peak_x": 3,
        "peak_value": 8,
    }


def test_caption_number_check_ignores_reference_labels() -> None:
    assert normalize_caption("Fig. 1: Mean accuracy", "line", "en") == "Figure 1. Mean accuracy"
    assert grounded("Figure 1. The mean is 80.", {80.0})
    assert not grounded("Figure 1. The mean is 81.", {80.0})
    assert grounded("As shown in Table 2, the mean is 80.", {80.0})
    assert allowed_numbers({"peak_x": "Q4", "value": 10}) >= {4.0, 10.0}


async def test_line_chart_returns_png_stats_and_grounded_caption(
    client: AsyncClient, session: Any, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import select

    from app.models.orm import Figure

    dataset = await _upload(client, CSV_LINE)
    _fake(
        monkeypatch,
        "Figure 1. Accuracy rises from 70 to 90, mean 80, peaking at 2022.",
        "图 1. 准确率从 70 升至 90，均值 80，峰值出现在 2022。",
    )
    response = await client.post(
        f"/api/v1/data/{dataset['id']}/chart",
        json={"type": "line", "x": "year", "y": ["accuracy"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    prefix = "data:image/png;base64,"
    assert body["image_url"].startswith(prefix)
    assert base64.b64decode(body["image_url"][len(prefix) :]).startswith(b"\x89PNG\r\n\x1a\n")
    assert body["caption"].startswith("Figure 1. Accuracy rises")
    assert body["caption_zh"].startswith("图 1.")
    assert body["stats"]["rows"] == 3
    accuracy = body["stats"]["series"]["accuracy"]
    assert (accuracy["min"], accuracy["max"], accuracy["mean"]) == (70, 90, 80)
    assert accuracy["change_rate"] == 0.2857
    assert accuracy["slope"] == 10.0
    assert accuracy["peak_x"] == 2022
    assert body["stats"]["x"]["min"] == 2020
    assert "ax.plot" in body["script"]

    figure = await session.scalar(select(Figure).where(Figure.dataset_id == dataset["id"]))
    assert figure is not None
    assert figure.caption == body["caption"]
    assert figure.stats["series"]["accuracy"]["peak_value"] == 90
    assert (data_dir / str(figure.render_path)).is_file()


async def test_invented_caption_number_falls_back_to_the_template(
    client: AsyncClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = await _upload(client, CSV_LINE)
    _fake(monkeypatch, "Figure 1. Accuracy reaches 99.9%.", "图 1. 准确率达到 99.9%。")
    response = await client.post(
        f"/api/v1/data/{dataset['id']}/chart",
        json={"type": "bar", "x": "year", "y": ["accuracy"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "99.9" not in body["caption"]
    assert "99.9" not in body["caption_zh"]
    assert "ranges from 70 to 90" in body["caption"]
    assert body["caption_zh"].startswith("图 1.")


async def test_chart_rejects_unknown_or_conflicting_columns(client: AsyncClient, data_dir: Path) -> None:
    dataset = await _upload(client, CSV_LINE)
    unknown = await client.post(
        f"/api/v1/data/{dataset['id']}/chart",
        json={"type": "line", "x": "year", "y": ["missing"]},
    )
    assert unknown.status_code == 400
    assert unknown.json()["error"]["detail"]["columns"] == ["missing"]

    conflict = await client.post(
        f"/api/v1/data/{dataset['id']}/chart",
        json={"type": "line", "x": "year", "y": ["year"]},
    )
    assert conflict.status_code == 400


async def test_missing_dataset_is_404(client: AsyncClient, data_dir: Path) -> None:
    response = await client.post("/api/v1/data/nope/chart", json={"type": "line", "x": "year", "y": ["accuracy"]})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("kind", ["radar", "radar3d"])
async def test_radar_requires_three_categories_and_renders(
    kind: str, client: AsyncClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    two = await _upload(client, "quarter,value\nQ1,10\nQ2,20\n", name="two.csv")
    rejected = await client.post(f"/api/v1/data/{two['id']}/chart", json={"type": kind, "x": "quarter", "y": ["value"]})
    assert rejected.status_code == 400
    assert rejected.json()["error"]["detail"]["categories"] == 2

    four = await _upload(client, "quarter,value\nQ1,10\nQ2,20\nQ3,30\nQ4,40\n", name="four.csv")
    _fake(monkeypatch, "Figure 1. Value is 10 in Q1 and 40 in Q4.")
    rendered = await client.post(
        f"/api/v1/data/{four['id']}/chart", json={"type": kind, "x": "quarter", "y": ["value"]}
    )
    assert rendered.status_code == 200, rendered.text
    body = rendered.json()
    assert body["stats"]["normalized"] == "min-max per series"
    assert body["image_url"].startswith("data:image/png;base64,")


async def test_table_chart_renders_a_still_image(
    client: AsyncClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = await _upload(client, "name,score\nA,1\nB,2\nC,3\n")
    _fake(monkeypatch, "Table 1. Scores by name.")
    response = await client.post(
        f"/api/v1/data/{dataset['id']}/chart",
        json={"type": "table", "x": "name", "y": ["score"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["caption"] == "Table 1. Scores by name."
    assert body["stats"]["series"]["score"]["n"] == 3
