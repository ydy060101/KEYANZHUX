import { humanMessage, toApiError } from "@/api/client";
import { splitFrames } from "@/features/qa/api";

import type { OutlineEvent, OutlineFlag, OutlineResult, OutlineSection, ReferenceCheck, WritingReference } from "./api.types";
import { optionalNumber, optionalText, record, records, strings, text } from "./api.wire";

function toReference(value: unknown): WritingReference | null {
  const row = record(value);
  if (!row || !text(row.title)) return null;
  return {
    key: text(row.key) || text(row.doi) || text(row.arxiv_id) || text(row.title),
    title: text(row.title),
    authors: strings(row.authors),
    year: optionalNumber(row.year),
    doi: optionalText(row.doi),
    arxivId: optionalText(row.arxiv_id),
    sourceUrl: optionalText(row.source_url),
    status: row.status === "unverified" ? "unverified" : "verified",
    similarity: optionalNumber(row.similarity),
  };
}

function toOutline(value: unknown): OutlineResult | null {
  const row = record(value);
  const outline = record(row?.outline);
  if (!row || !outline || !text(row.draft_id)) return null;
  const sections = records(outline.sections).flatMap((item): OutlineSection[] => {
    const heading = text(item.heading);
    if (!heading) return [];
    return [{ heading, markdown: text(item.markdown) }];
  });
  const markdown = text(outline.markdown) || sections.map((item) => `## ${item.heading}\n\n${item.markdown}`).join("\n\n");
  const references = Array.isArray(row.references) ? row.references : [];
  return {
    draftId: text(row.draft_id),
    title: text(outline.title) || "Untitled outline",
    markdown,
    sections,
    references: references.flatMap((item): WritingReference[] => {
      const reference = toReference(item);
      return reference ? [reference] : [];
    }),
    bibtex: text(row.bibtex),
    flags: records(row.flags).flatMap((flag): OutlineFlag[] => {
      const message = text(flag.text);
      return message ? [{ kind: text(flag.kind), section: text(flag.section), text: message }] : [];
    }),
  };
}

function toOutlineEvent(event: string, raw: string): OutlineEvent | null {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  const row = record(value);
  if (!row) return null;
  if (event === "stage") {
    const stage = text(row.stage);
    const message = text(row.message);
    if (!stage || !message) return null;
    return { type: "stage", stage, message, count: optionalNumber(row.count) };
  }
  if (event === "done") {
    const data = toOutline(value);
    return data ? { type: "done", data } : null;
  }
  if (event === "error") return { type: "error", message: humanMessage(toApiError(value)) };
  return null;
}

/** POST /writing/outline and decode its SSE frames. */
export async function streamOutline(
  input: { idea: string; language: "zh" | "en"; venue?: string | null },
  onEvent: (event: OutlineEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch("/api/v1/writing/outline", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      "X-User-Id": "default",
    },
    body: JSON.stringify({ idea: input.idea, language: input.language, venue: input.venue ?? null }),
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
        const event = toOutlineEvent(frame.event, frame.data);
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
  if (!signal?.aborted) throw new Error("生成中断，请重试");
}

export async function verifyTitles(titles: string[]): Promise<ReferenceCheck[]> {
  const response = await fetch("/api/v1/writing/references/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-User-Id": "default" },
    body: JSON.stringify({ titles }),
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new Error(humanMessage(toApiError(payload)));
  if (!Array.isArray(payload)) throw new Error("校验结果格式不正确");
  return payload.flatMap((item): ReferenceCheck[] => {
    const row = record(item);
    if (!row || !text(row.title)) return [];
    return [
      {
        title: text(row.title),
        status: row.status === "verified" ? "verified" : "unverified",
        sourceUrl: optionalText(row.source_url),
        arxivId: optionalText(row.arxiv_id),
        doi: optionalText(row.doi),
      },
    ];
  });
}

export async function fetchBibtex(draftId: string): Promise<string> {
  const response = await fetch(`/api/v1/writing/drafts/${encodeURIComponent(draftId)}/bibtex`, {
    headers: { "X-User-Id": "default" },
  });
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null);
    throw new Error(humanMessage(toApiError(payload)));
  }
  return response.text();
}

/** Citation keys used by the draft, in document order. */
export function citationKeys(markdown: string): string[] {
  const found: string[] = [];
  for (const match of markdown.matchAll(/\\cite\{([^}]*)\}/g)) {
    for (const raw of (match[1] ?? "").split(",")) {
      const key = raw.trim();
      if (key && !found.includes(key)) found.push(key);
    }
  }
  return found;
}
