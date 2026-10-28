import { humanMessage, toApiError } from "@/api/client";

/**
 * Wire types for `/graphs` (T6.1/T6.2).
 *
 * The contract marks most metric fields optional, so reading a graph is done
 * through `toGraph`, which defaults them: the canvas needs numbers, and an
 * older graph without `betweenness` must still render. Node and edge identity
 * is never invented — a payload without them is rejected.
 */

export type GraphRole = "cornerstone" | "middle" | "peripheral";
export type GraphLayout = "force" | "timeline";

export interface GraphNodeView {
  id: string;
  title: string;
  year: number | null;
  role: GraphRole;
  pagerank: number;
  inDegree: number;
  outDegree: number;
  betweenness: number;
  reason: string;
}

export interface GraphEdgeView {
  source: string;
  target: string;
  method: string;
  confidence: number;
  contexts: string[];
}

export interface GraphView {
  id: string;
  nodes: GraphNodeView[];
  edges: GraphEdgeView[];
  metrics: Record<string, unknown>;
}

export const ROLE_LABEL: Record<GraphRole, string> = {
  cornerstone: "基石",
  middle: "中间",
  peripheral: "边缘",
};

export const ROLE_ORDER: GraphRole[] = ["cornerstone", "middle", "peripheral"];

export const METHOD_LABEL: Record<string, string> = {
  doi: "DOI",
  arxiv_id: "arXiv ID",
  title: "标题",
  raw_prefix: "文首前缀",
};

export const graphKeys = { detail: (id: string) => ["graph", id] as const };

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function number(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function role(value: unknown): GraphRole {
  return value === "cornerstone" || value === "peripheral" ? value : "middle";
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

export function toGraph(value: unknown): GraphView | null {
  const row = record(value);
  if (!row || !text(row.id)) return null;

  const nodes: GraphNodeView[] = [];
  for (const item of Array.isArray(row.nodes) ? row.nodes : []) {
    const node = record(item);
    if (!node || !text(node.id) || !text(node.title)) continue;
    nodes.push({
      id: text(node.id),
      title: text(node.title),
      year: typeof node.year === "number" ? node.year : null,
      role: role(node.role),
      pagerank: number(node.pagerank),
      inDegree: number(node.in_degree),
      outDegree: number(node.out_degree),
      betweenness: number(node.betweenness),
      reason: text(node.reason),
    });
  }

  const known = new Set(nodes.map((node) => node.id));
  const edges: GraphEdgeView[] = [];
  for (const item of Array.isArray(row.edges) ? row.edges : []) {
    const edge = record(item);
    if (!edge) continue;
    const source = text(edge.source);
    const target = text(edge.target);
    if (!known.has(source) || !known.has(target)) continue;
    edges.push({
      source,
      target,
      method: text(edge.method) || "title",
      confidence: number(edge.confidence),
      contexts: strings(edge.contexts),
    });
  }

  return { id: text(row.id), nodes, edges, metrics: record(row.metrics) ?? {} };
}

function metricList(metrics: Record<string, unknown>, key: string): string[] {
  return strings(metrics[key]);
}

function metricNumber(metrics: Record<string, unknown>, key: string): number | null {
  const value = metrics[key];
  return typeof value === "number" ? value : null;
}

export interface GraphHighlights {
  cornerstone: string[];
  peripheral: string[];
  nodeCount: number | null;
  edgeCount: number | null;
  unmatched: number | null;
  isolated: string[];
}

export function highlights(metrics: Record<string, unknown>): GraphHighlights {
  return {
    cornerstone: metricList(metrics, "cornerstone"),
    peripheral: metricList(metrics, "peripheral"),
    nodeCount: metricNumber(metrics, "node_count"),
    edgeCount: metricNumber(metrics, "edge_count"),
    unmatched: metricNumber(metrics, "unmatched_references"),
    isolated: metricList(metrics, "isolated"),
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

export async function fetchGraph(id: string): Promise<GraphView> {
  const graph = toGraph(await request(`/graphs/${encodeURIComponent(id)}`));
  if (!graph) throw new Error("图谱数据格式异常，请重新生成");
  return graph;
}

export interface GraphJob {
  id: string;
  status: string;
}

export async function createGraph(docIds: string[]): Promise<GraphJob> {
  const payload = record(await request("/graphs", { method: "POST", body: JSON.stringify({ doc_ids: docIds }) }));
  if (!payload || !text(payload.id)) throw new Error("任务创建失败，请重试");
  return { id: text(payload.id), status: text(payload.status) || "queued" };
}
