import { humanMessage, toApiError } from "@/api/client";

import type {
  AcademicTranslation,
  ChartKind,
  ChartResult,
  DatasetColumn,
  DatasetView,
  FigureKind,
  FigureResult,
} from "./api.types";
import { optionalNumber, optionalText, record, records, strings, text } from "./api.wire";

function toFigure(value: unknown, kind: FigureKind): FigureResult {
  const row = record(value) ?? {};
  return {
    kind,
    script: text(row.script),
    rendered: optionalText(row.rendered),
    errors: strings(row.errors),
    notes: strings(row.notes),
    renderer: text(row.renderer),
    attempts: optionalNumber(row.attempts) ?? 0,
  };
}

export async function generateFigure(kind: FigureKind, description: string): Promise<FigureResult> {
  const response = await fetch("/api/v1/figures/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-User-Id": "default" },
    body: JSON.stringify({ kind, description }),
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new Error(humanMessage(toApiError(payload)));
  return toFigure(payload, kind);
}

export async function runFigure(kind: FigureKind, script: string): Promise<FigureResult> {
  const response = await fetch("/api/v1/figures/run", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-User-Id": "default" },
    body: JSON.stringify({ kind, script }),
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new Error(humanMessage(toApiError(payload)));
  return toFigure(payload, kind);
}

export async function uploadDataset(file: File): Promise<DatasetView> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch("/api/v1/data/upload", {
    method: "POST",
    headers: { "X-User-Id": "default" },
    body: form,
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new Error(humanMessage(toApiError(payload)));
  const row = record(payload);
  if (!row || !text(row.id)) throw new Error("数据集解析失败");
  const columns = Array.isArray(row.columns)
    ? row.columns.flatMap((item): DatasetColumn[] => {
        const column = record(item);
        if (!column || !text(column.name)) return [];
        return [
          {
            name: text(column.name),
            dtype: text(column.dtype) || "unknown",
            missingRate: optionalNumber(column.missing_rate) ?? 0,
          },
        ];
      })
    : [];
  return {
    id: text(row.id),
    filename: text(row.filename) || "dataset.csv",
    rowCount: optionalNumber(row.row_count) ?? 0,
    columns,
    preview: records(row.preview),
  };
}

export async function createChart(
  datasetId: string,
  request: { type: ChartKind; x: string; y: string[] },
): Promise<ChartResult> {
  const response = await fetch(`/api/v1/data/${encodeURIComponent(datasetId)}/chart`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-User-Id": "default" },
    body: JSON.stringify(request),
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new Error(humanMessage(toApiError(payload)));
  const row = record(payload);
  if (!row || !text(row.image_url)) throw new Error("图表渲染失败");
  return {
    imageUrl: text(row.image_url),
    script: text(row.script),
    stats: record(row.stats) ?? {},
    caption: text(row.caption),
    captionZh: text(row.caption_zh),
  };
}

export async function translateAcademic(value: string): Promise<AcademicTranslation> {
  const response = await fetch("/api/v1/translate/zh2en", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-User-Id": "default" },
    body: JSON.stringify({ text: value, direction: "zh2en" }),
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new Error(humanMessage(toApiError(payload)));
  const row = record(payload);
  if (!row || typeof row.text !== "string") throw new Error("译文格式不正确");
  return { text: row.text, cached: row.cached === true };
}
