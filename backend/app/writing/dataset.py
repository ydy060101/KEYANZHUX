"""CSV datasets for the data workshop (T7.3).

The uploaded file is parsed once, normalised to UTF-8 and stored under
`data/datasets/`; the database row keeps the relative path, the column profile
and the row count. Nothing here trusts the client's filename beyond a display
label and the `.csv` suffix.
"""

from __future__ import annotations

import asyncio
import io
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..errors import InvalidRequest, PayloadTooLarge, UnsupportedMedia
from ..models.orm import Dataset, new_id

MAX_CSV_BYTES = 20 * 1024 * 1024
MAX_ROWS = 200_000
MAX_COLUMNS = 200
PREVIEW_ROWS = 20

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def safe_filename(name: str | None) -> str:
    base = Path(name or "dataset.csv").name
    base = _CONTROL.sub("", base).strip()
    if not base.lower().endswith(".csv"):
        raise UnsupportedMedia("只支持 CSV 文件")
    return base[:120] or "dataset.csv"


def decode_csv(raw: bytes) -> str:
    if not raw.strip():
        raise InvalidRequest("CSV 文件为空")
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise InvalidRequest("无法识别 CSV 编码，请另存为 UTF-8")


def parse_csv(text: str) -> pd.DataFrame:
    try:
        frame = pd.read_csv(io.StringIO(text), low_memory=False)
    except (pd.errors.ParserError, ValueError) as exc:
        raise InvalidRequest("CSV 解析失败", detail={"reason": str(exc)}) from exc
    frame = frame.dropna(how="all")
    if frame.empty or len(frame.columns) == 0:
        raise InvalidRequest("CSV 没有数据行")
    if len(frame) > MAX_ROWS:
        raise InvalidRequest(f"数据行数超过上限 {MAX_ROWS}", detail={"rows": len(frame)})
    if len(frame.columns) > MAX_COLUMNS:
        raise InvalidRequest(f"列数超过上限 {MAX_COLUMNS}", detail={"columns": len(frame.columns)})
    frame.columns = [str(column) for column in frame.columns]
    return frame


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if hasattr(value, "item"):
        item = value.item()
        return None if isinstance(item, float) and pd.isna(item) else item
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def column_profile(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {
            "name": str(column),
            "dtype": str(frame[column].dtype),
            "missing_rate": round(float(frame[column].isna().mean()), 4),
        }
        for column in frame.columns
    ]


def preview_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in frame.head(PREVIEW_ROWS).to_dict(orient="records"):
        rows.append({str(key): _json_value(value) for key, value in record.items()})
    return rows


def dataset_payload(row: Dataset, frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "id": row.id,
        "filename": row.filename,
        "row_count": row.row_count,
        "columns": row.columns,
        "preview": preview_rows(frame),
    }


def _dataset_dir() -> Path:
    folder = get_settings().data_dir / "datasets"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


async def create_dataset(session: AsyncSession, raw: bytes, filename: str) -> tuple[Dataset, pd.DataFrame]:
    if len(raw) > MAX_CSV_BYTES:
        raise PayloadTooLarge(f"CSV 不能超过 {MAX_CSV_BYTES // (1024 * 1024)} MB")
    safe = safe_filename(filename)
    text = decode_csv(raw)
    frame = parse_csv(text)

    dataset_id = new_id()
    path = _dataset_dir() / f"{dataset_id}.csv"
    await asyncio.to_thread(path.write_text, text, "utf-8")
    row = Dataset(
        id=dataset_id,
        filename=safe,
        path=path.relative_to(get_settings().data_dir).as_posix(),
        columns=column_profile(frame),
        row_count=int(len(frame)),
    )
    session.add(row)
    await session.commit()
    return row, frame


def load_frame(row: Dataset) -> pd.DataFrame:
    base = get_settings().data_dir.resolve()
    path = (base / row.path).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        raise InvalidRequest("数据集文件不存在，请重新上传")
    try:
        return pd.read_csv(path, low_memory=False)
    except (pd.errors.ParserError, ValueError, OSError) as exc:
        raise InvalidRequest("数据集读取失败", detail={"reason": str(exc)}) from exc
