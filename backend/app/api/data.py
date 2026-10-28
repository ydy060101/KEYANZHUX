"""CSV datasets and chart rendering (01 §5.6, T7.3).

`POST /data/upload` parses the CSV once and returns the contract's column
profile and preview. `POST /data/{id}/chart` computes stats, asks the model for
a caption, verifies every number in it against those stats, renders a PNG and
persists the figure. The caption falls back to a deterministic template when
the model is unavailable or invents a number, so a chart never fails because of
the language model (H08).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel, Field

from ..config import get_settings
from ..deps import SessionDep
from ..errors import AppError, InvalidRequest, NotFound
from ..llm.gateway import get_gateway
from ..models.orm import Dataset, Figure, new_id
from ..writing import chart as chart_service
from ..writing import dataset as dataset_service
from ..writing.caption import make_caption
from ..writing.chart import ChartKind
from ..writing.chart_script import script_for

logger = logging.getLogger(__name__)

router = APIRouter(tags=["data"])


class ChartBody(BaseModel):
    type: ChartKind
    x: str = Field(min_length=1, max_length=200)
    y: list[str] = Field(min_length=1, max_length=chart_service.MAX_SERIES)


@router.post("/data/upload")
async def upload_dataset(session: SessionDep, file: UploadFile = File(...)) -> dict[str, Any]:
    raw = await file.read(dataset_service.MAX_CSV_BYTES + 1)
    row, frame = await dataset_service.create_dataset(session, raw, file.filename or "")
    return dataset_service.dataset_payload(row, frame)


@router.post("/data/{dataset_id}/chart")
async def create_chart(dataset_id: str, body: ChartBody, session: SessionDep) -> dict[str, Any]:
    row = await session.get(Dataset, dataset_id)
    if row is None:
        raise NotFound("数据集不存在")

    x = body.x.strip()
    ys: list[str] = []
    for raw_name in body.y:
        name = raw_name.strip()
        if name and name not in ys:
            ys.append(name)
    if not ys:
        raise InvalidRequest("请至少选择一列 y")
    if x in ys:
        raise InvalidRequest("x 与 y 不能是同一列")

    frame = await asyncio.to_thread(dataset_service.load_frame, row)
    prepared = await asyncio.to_thread(chart_service.prepare, frame, x, ys, body.type)
    stats = chart_service.compute_stats(prepared, x, ys, body.type)
    caption, caption_zh = await make_caption(get_gateway(), stats, body.type, x, ys)

    figure_id = new_id()
    path = chart_service.figure_path(figure_id)
    try:
        await asyncio.to_thread(chart_service.render_chart, prepared, x, ys, body.type, path)
        image_url = await asyncio.to_thread(chart_service.png_data_url, path)
    except AppError:
        raise
    except Exception as exc:  # reported as a readable 500, never a silent break
        logger.exception("chart render failed")
        raise AppError(
            "图表渲染失败，请更换图表类型或数据列",
            code="render_failed",
            status_code=500,
            detail={"type": type(exc).__name__},
        ) from exc

    script = script_for(x, ys, body.type)
    figure = Figure(
        id=figure_id,
        dataset_id=row.id,
        kind=body.type,
        script=script,
        render_path=path.relative_to(get_settings().data_dir).as_posix(),
        caption=caption,
        stats=stats,
    )
    session.add(figure)
    await session.commit()
    return {
        "image_url": image_url,
        "script": script,
        "stats": stats,
        "caption": caption,
        "caption_zh": caption_zh,
    }
