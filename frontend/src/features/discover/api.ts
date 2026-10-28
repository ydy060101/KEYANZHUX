import { humanMessage, toApiError } from "@/api/client";

/**
 * Wire types for `/discover/*` and `/recommendations` (T5.1/T5.6).
 *
 * `ScholarHit` and `Recommendation` carry `ext_id` / `source` beyond the
 * contract's fields: the import endpoint is keyed by `{source, ext_id}`, so a
 * hit without them could be displayed but not imported. They are additive
 * properties, which the schema permits.
 */
export interface ScholarHit {
  title: string;
  source: string;
  ext_id: string;
  authors: string[];
  year: number | null;
  abstract: string | null;
  arxiv_id: string | null;
  doi: string | null;
  pdf_url: string | null;
  github_url: string | null;
  stars: number | null;
  in_library: boolean;
}

export interface Recommendation {
  paper_id: string;
  title: string;
  source: string;
  authors: string[];
  year: number | null;
  score: number;
  reasons: string[];
  abstract: string | null;
  pdf_url: string | null;
  github_url: string | null;
  stars: number | null;
}

export interface ImportJob {
  id: string;
  status: string;
}

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function optionalText(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function optionalNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function toHit(value: unknown): ScholarHit | null {
  const row = record(value);
  // A hit without an id cannot be imported (`/discover/fetch` is keyed by
  // `{source, ext_id}`), so showing it would offer an action that must fail.
  if (!row || !text(row.title) || !text(row.ext_id)) return null;
  return {
    title: text(row.title),
    source: text(row.source),
    ext_id: text(row.ext_id),
    authors: strings(row.authors),
    year: optionalNumber(row.year),
    abstract: optionalText(row.abstract),
    arxiv_id: optionalText(row.arxiv_id),
    doi: optionalText(row.doi),
    pdf_url: optionalText(row.pdf_url),
    github_url: optionalText(row.github_url),
    stars: optionalNumber(row.stars),
    in_library: row.in_library === true,
  };
}

function toRecommendation(value: unknown): Recommendation | null {
  const row = record(value);
  if (!row || !text(row.paper_id) || !text(row.title)) return null;
  return {
    paper_id: text(row.paper_id),
    title: text(row.title),
    source: text(row.source),
    authors: strings(row.authors),
    year: optionalNumber(row.year),
    score: optionalNumber(row.score) ?? 0,
    reasons: strings(row.reasons),
    abstract: optionalText(row.abstract),
    pdf_url: optionalText(row.pdf_url),
    github_url: optionalText(row.github_url),
    stars: optionalNumber(row.stars),
  };
}

async function request(path: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(`/api/v1${path}`, {
    headers: { "Content-Type": "application/json", "X-User-Id": "default" },
    ...init,
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new Error(humanMessage(toApiError(payload)));
  return payload;
}

/** Human names for the four providers; unknown keys pass through. */
const SOURCE_LABELS: Record<string, string> = {
  arxiv: "arXiv",
  semanticscholar: "Semantic Scholar",
  openalex: "OpenAlex",
  crossref: "Crossref",
};

export function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source;
}

export interface SearchResult {
  hits: ScholarHit[];
  /** Sources the backend could not reach; the result is partial (H08). */
  degraded: string[];
}

/** Read the RFC 7234 `Warning` the API adds when a source failed. */
function degradedSources(response: Response): string[] {
  const warning = response.headers.get("Warning");
  const match = warning ? /"(.*?) unavailable"/.exec(warning) : null;
  return match?.[1] ? match[1].split(/\s+/).filter(Boolean) : [];
}

export async function searchPapers(query: string, limit = 10): Promise<SearchResult> {
  const response = await fetch("/api/v1/discover/search", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-User-Id": "default" },
    body: JSON.stringify({ query, limit }),
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new Error(humanMessage(toApiError(payload)));
  if (!Array.isArray(payload)) throw new Error("检索结果格式不正确");
  return {
    hits: payload.flatMap((item): ScholarHit[] => {
      const hit = toHit(item);
      return hit ? [hit] : [];
    }),
    degraded: degradedSources(response),
  };
}

export async function fetchRecommendations(limit = 12): Promise<Recommendation[]> {
  const payload = await request(`/recommendations?limit=${limit}`);
  if (!Array.isArray(payload)) throw new Error("推荐结果格式不正确");
  return payload.flatMap((item): Recommendation[] => {
    const row = toRecommendation(item);
    return row ? [row] : [];
  });
}

/** Queue the import; the download and parse run as a job (H07). */
export async function importPaper(source: string, extId: string): Promise<ImportJob> {
  const payload = await request("/discover/fetch", {
    method: "POST",
    body: JSON.stringify({ source, ext_id: extId }),
  });
  const row = record(payload);
  if (!row || !text(row.id)) throw new Error("导入任务创建失败");
  return { id: text(row.id), status: text(row.status) };
}
