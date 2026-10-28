import { humanMessage, toApiError } from "@/api/client";
import { splitFrames } from "@/features/qa/api";

export type Direction = "en2zh" | "zh2en";

export interface SelectionDone {
  text: string;
  direction: Direction;
  repaired: boolean;
  placeholders: number;
  first_token_ms: number | null;
  elapsed_ms: number;
}

export type TranslationEvent =
  | { type: "token"; text: string }
  | { type: "done"; data: SelectionDone }
  | { type: "error"; message: string };

export interface TranslationBlock {
  block_id: string;
  page: number;
  type: string;
  bbox: number[];
  original: string;
  translation: string;
}

export interface DocumentTranslation {
  doc_id: string;
  direction: Direction;
  lang: string;
  blocks: TranslationBlock[];
}

export interface GlossaryEntry {
  source: string;
  target: string;
}

export interface Glossary {
  version: number;
  entries: GlossaryEntry[];
  updated_at: string | null;
}

function toGlossary(payload: unknown): Glossary {
  const row = record(payload);
  const entries = Array.isArray(row?.entries) ? row.entries : [];
  return {
    version: typeof row?.version === "number" ? row.version : 0,
    updated_at: typeof row?.updated_at === "string" ? row.updated_at : null,
    entries: entries.flatMap((item): GlossaryEntry[] => {
      const entry = record(item);
      if (!entry || typeof entry.source !== "string" || typeof entry.target !== "string") return [];
      return [{ source: entry.source, target: entry.target }];
    }),
  };
}

export async function fetchGlossary(): Promise<Glossary> {
  const response = await fetch("/api/v1/translate/glossary", {
    headers: { "X-User-Id": "default" },
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new Error(humanMessage(toApiError(payload)));
  return toGlossary(payload);
}

/** Replace the list; returns the version the next translation will use. */
export async function saveGlossary(entries: GlossaryEntry[]): Promise<Glossary> {
  const response = await fetch("/api/v1/translate/glossary", {
    method: "PUT",
    headers: { "Content-Type": "application/json", "X-User-Id": "default" },
    body: JSON.stringify({ entries }),
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new Error(humanMessage(toApiError(payload)));
  return toGlossary(payload);
}

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function toEvent(event: string, raw: string): TranslationEvent | null {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  const row = record(value);
  if (!row) return null;
  if (event === "token") {
    return typeof row.text === "string" ? { type: "token", text: row.text } : null;
  }
  if (event === "done") {
    if (typeof row.text !== "string") return null;
    return {
      type: "done",
      data: {
        text: row.text,
        direction: row.direction === "zh2en" ? "zh2en" : "en2zh",
        repaired: row.repaired === true,
        placeholders: typeof row.placeholders === "number" ? row.placeholders : 0,
        first_token_ms: typeof row.first_token_ms === "number" ? row.first_token_ms : null,
        elapsed_ms: typeof row.elapsed_ms === "number" ? row.elapsed_ms : 0,
      },
    };
  }
  if (event === "error") {
    return { type: "error", message: humanMessage(toApiError(value)) };
  }
  return null;
}

/**
 * Translate a selection and stream the result (T4.1).
 *
 * `POST /translate/selection` is a POST stream, so EventSource cannot be used;
 * the body is decoded frame by frame. Aborting the signal cancels the request
 * and the backend task.
 */
export async function translateSelection(
  text: string,
  direction: Direction,
  onEvent: (event: TranslationEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch("/api/v1/translate/selection", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      "X-User-Id": "default",
    },
    body: JSON.stringify({ text, direction }),
    ...(signal ? { signal } : {}),
  });
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null);
    throw new Error(humanMessage(toApiError(payload)));
  }
  if (!response.body) throw new Error("浏览器不支持流式响应");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const split = splitFrames(buffer);
      buffer = split.rest;
      for (const frame of split.frames) {
        const event = toEvent(frame.event, frame.data);
        if (!event) continue;
        onEvent(event);
        if (event.type === "done" || event.type === "error") {
          await reader.cancel().catch(() => undefined);
          return;
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export async function fetchTranslation(
  docId: string,
  direction: Direction,
): Promise<DocumentTranslation> {
  const params = new URLSearchParams({ direction });
  const response = await fetch(
    `/api/v1/documents/${encodeURIComponent(docId)}/translation?${params.toString()}`,
    { headers: { "X-User-Id": "default" } },
  );
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new Error(humanMessage(toApiError(payload)));
  const row = record(payload);
  const blocks = Array.isArray(row?.blocks) ? row.blocks : [];
  return {
    doc_id: docId,
    direction,
    lang: typeof row?.lang === "string" ? row.lang : "zh",
    blocks: blocks.flatMap((item): TranslationBlock[] => {
      const block = record(item);
      if (!block || typeof block.block_id !== "string") return [];
      return [
        {
          block_id: block.block_id,
          page: typeof block.page === "number" ? block.page : 0,
          type: typeof block.type === "string" ? block.type : "paragraph",
          bbox: Array.isArray(block.bbox) ? block.bbox.filter((n): n is number => typeof n === "number") : [],
          original: typeof block.original === "string" ? block.original : "",
          translation: typeof block.translation === "string" ? block.translation : "",
        },
      ];
    }),
  };
}

export async function startDocumentTranslation(
  docId: string,
  direction: Direction,
  format: "md" | "html" = "md",
): Promise<{ job_id: string; direction: Direction }> {
  const response = await fetch(`/api/v1/documents/${encodeURIComponent(docId)}/translate`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-User-Id": "default" },
    body: JSON.stringify({ format, direction }),
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new Error(humanMessage(toApiError(payload)));
  const row = record(payload);
  if (typeof row?.job_id !== "string") throw new Error("任务创建失败");
  return { job_id: row.job_id, direction: row.direction === "zh2en" ? "zh2en" : "en2zh" };
}

/** Fetch the rendered translation and hand it to the browser as a file. */
export async function downloadTranslation(
  docId: string,
  direction: Direction,
  format: "md" | "html",
): Promise<void> {
  const params = new URLSearchParams({ direction, format });
  const response = await fetch(
    `/api/v1/documents/${encodeURIComponent(docId)}/translation?${params.toString()}`,
    { headers: { "X-User-Id": "default" } },
  );
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new Error(humanMessage(toApiError(payload)));
  const row = record(payload);
  if (typeof row?.content !== "string") throw new Error("译文尚未生成");
  const blob = new Blob([row.content], {
    type: format === "html" ? "text/html;charset=utf-8" : "text/markdown;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${docId}.${row.lang === "en" ? "en" : "zh"}.${format}`;
  anchor.click();
  URL.revokeObjectURL(url);
}
