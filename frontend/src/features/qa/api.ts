import { humanMessage, toApiError } from "@/api/client";

/** The QA contract as the UI consumes it (openapi `QARequest`/`QAAnswer`).
 *
 *  The generated types mark every field optional; the backend always sends
 *  `answer`, `citations` and `refused`, so the parser below validates the JSON
 *  once and the components get strict types. A malformed frame is dropped
 *  rather than rendered as a half-invented citation (H02).
 */

export type QaMode = "qa" | "compare";
export type QaScopeType = "doc" | "set" | "all";

export interface QaScope {
  type: QaScopeType;
  doc_ids: string[];
}

export interface QaAnchor {
  doc_id: string;
  block_id: string;
  page: number;
  bbox: number[];
}

export interface QaCitation {
  marker: string;
  anchor: QaAnchor;
  quote: string;
}

export type QaFlagKind = "invalid_citation" | "ungrounded_number" | "uncited_claim" | "weak_support";

export interface QaFlag {
  kind: QaFlagKind;
  text: string;
}

export interface QaAnswer {
  answer: string;
  citations: QaCitation[];
  refused: boolean;
  flags: QaFlag[];
}

export interface CompareCell {
  text: string;
  citations: QaAnchor[];
}

export interface CompareRow {
  dimension: string;
  cells: Record<string, CompareCell>;
}

export interface CompareTable {
  dimensions: string[];
  table: CompareRow[];
  summary: string;
  flags: QaFlag[];
}

export interface QaDone extends QaAnswer {
  documents?: Record<string, string>;
  table?: CompareTable;
}

export type QaEvent =
  | { type: "token"; text: string }
  | { type: "anchor"; marker: string; anchor: QaAnchor; quote: string }
  | { type: "done"; data: QaDone }
  | { type: "error"; message: string };

export const NOT_FOUND = "未在原文找到";

/** A conversation turn, including the streaming state the page renders. */
export interface QaTurn {
  id: string;
  question: string;
  answer: string;
  citations: QaCitation[];
  refused: boolean;
  flags: QaFlag[];
  status: "streaming" | "done" | "error";
  error?: string;
  table?: CompareTable;
  documents?: Record<string, string>;
  createdAt: string;
}

export interface QaRequest {
  question: string;
  scope: QaScope;
  mode: QaMode;
  session_id?: string;
}

interface SseFrame {
  event: string;
  data: string;
}

// ---- JSON guards ---------------------------------------------------------

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function text(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function anchor(value: unknown): QaAnchor | null {
  const row = record(value);
  if (!row) return null;
  const docId = text(row.doc_id);
  const blockId = text(row.block_id);
  const page = finite(row.page);
  const bbox = Array.isArray(row.bbox)
    ? row.bbox.map(finite).filter((item): item is number => item !== null)
    : [];
  if (!docId || !blockId || page === null) return null;
  return { doc_id: docId, block_id: blockId, page, bbox };
}

const FLAG_KINDS = new Set<QaFlagKind>([
  "invalid_citation",
  "ungrounded_number",
  "uncited_claim",
  "weak_support",
]);

function flags(value: unknown): QaFlag[] {
  if (!Array.isArray(value)) return [];
  const parsed: QaFlag[] = [];
  for (const item of value) {
    const row = record(item);
    const kind = row ? text(row.kind) : null;
    const message = row ? text(row.text) : null;
    if (kind && FLAG_KINDS.has(kind as QaFlagKind) && message) {
      parsed.push({ kind: kind as QaFlagKind, text: message });
    }
  }
  return parsed;
}

function citations(value: unknown): QaCitation[] {
  if (!Array.isArray(value)) return [];
  const parsed: QaCitation[] = [];
  for (const item of value) {
    const row = record(item);
    if (!row) continue;
    const marker = text(row.marker);
    const parsedAnchor = anchor(row.anchor);
    if (!marker || !parsedAnchor) continue;
    parsed.push({ marker, anchor: parsedAnchor, quote: text(row.quote) ?? "" });
  }
  return parsed;
}

function table(value: unknown): CompareTable | null {
  const row = record(value);
  if (!row || !Array.isArray(row.table)) return null;
  const dimensions = Array.isArray(row.dimensions)
    ? row.dimensions.map(text).filter((item): item is string => item !== null)
    : [];
  const rows: CompareRow[] = [];
  for (const item of row.table) {
    const entry = record(item);
    const dimension = entry ? text(entry.dimension) : null;
    const cells = entry ? record(entry.cells) : null;
    if (!dimension || !cells) continue;
    const parsedCells: Record<string, CompareCell> = {};
    for (const [docId, cellValue] of Object.entries(cells)) {
      const cell = record(cellValue);
      const cellText = cell ? text(cell.text) : null;
      if (!cell || cellText === null) continue;
      parsedCells[docId] = {
        text: cellText,
        citations: Array.isArray(cell.citations)
          ? cell.citations.map(anchor).filter((item): item is QaAnchor => item !== null)
          : [],
      };
    }
    rows.push({ dimension, cells: parsedCells });
  }
  return {
    dimensions,
    table: rows,
    summary: text(row.summary) ?? "",
    flags: flags(row.flags),
  };
}

function answer(value: unknown): QaDone | null {
  const row = record(value);
  if (!row) return null;
  const body = text(row.answer);
  if (body === null) return null;
  const parsed: QaDone = {
    answer: body,
    citations: citations(row.citations),
    refused: row.refused === true,
    flags: flags(row.flags),
  };
  const documents = record(row.documents);
  if (documents) {
    const titles: Record<string, string> = {};
    for (const [docId, title] of Object.entries(documents)) {
      const parsedTitle = text(title);
      if (parsedTitle) titles[docId] = parsedTitle;
    }
    parsed.documents = titles;
  }
  const parsedTable = table(row.table);
  if (parsedTable) parsed.table = parsedTable;
  return parsed;
}

// ---- SSE ----------------------------------------------------------------

/** Split complete SSE frames from a buffer, returning the incomplete tail. */
export function splitFrames(buffer: string): { frames: SseFrame[]; rest: string } {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const parts = normalized.split("\n\n");
  const rest = parts.pop() ?? "";
  const frames: SseFrame[] = [];
  for (const part of parts) {
    const frame = parseFrame(part);
    if (frame) frames.push(frame);
  }
  return { frames, rest };
}

function parseFrame(raw: string): SseFrame | null {
  let event = "message";
  const data: string[] = [];
  for (const line of raw.split("\n")) {
    // A line starting with `:` is an SSE comment, which is what the server's
    // ten-second keepalive is.
    if (line.startsWith(":")) continue;
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trim());
  }
  if (data.length === 0) return null;
  return { event, data: data.join("\n") };
}

function toEvent(frame: SseFrame): QaEvent | null {
  let value: unknown;
  try {
    value = JSON.parse(frame.data);
  } catch {
    return null;
  }
  const row = record(value);
  if (!row) return null;
  switch (frame.event) {
    case "token": {
      const body = text(row.text);
      return body === null ? null : { type: "token", text: body };
    }
    case "anchor": {
      const marker = text(row.marker);
      const parsedAnchor = anchor(row.anchor);
      if (!marker || !parsedAnchor) return null;
      return { type: "anchor", marker, anchor: parsedAnchor, quote: text(row.quote) ?? "" };
    }
    case "done": {
      const parsed = answer(value);
      return parsed ? { type: "done", data: parsed } : null;
    }
    case "error":
      return { type: "error", message: humanMessage(toApiError(value)) };
    default:
      return null;
  }
}

/**
 * Ask one question and stream its events.
 *
 * `POST /qa` is a POST stream, so EventSource (GET only) cannot be used; the
 * fetch body is decoded frame by frame. Aborting the controller cancels the
 * request and the backend task.
 */
export async function askQuestion(
  request: QaRequest,
  onEvent: (event: QaEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch("/api/v1/qa", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream", "X-User-Id": "default" },
    body: JSON.stringify(request),
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
        const event = toEvent(frame);
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

/** A reader link that lands on a page and highlights an anchor's bbox. */
export function readerHref(anchorValue: QaAnchor, embed = false): string {
  const params = new URLSearchParams({ page: String(anchorValue.page) });
  if (anchorValue.bbox.length === 4) params.set("bbox", anchorValue.bbox.join(","));
  const base = embed ? "/embed/reader" : "/reader";
  return `${base}/${encodeURIComponent(anchorValue.doc_id)}?${params.toString()}`;
}
