import { ExternalLink, GitFork, Network } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { EmptyState } from "@/design/States";
import { METHOD_LABEL, ROLE_LABEL, type GraphNodeView, type GraphView } from "@/features/graph/api";
import { cn } from "@/lib/cn";

type Tab = "metrics" | "survey" | "future";

const TABS: [Tab, string][] = [
  ["metrics", "指标榜"],
  ["survey", "综述"],
  ["future", "Future Work"],
];

function metric(value: number, digits = 3): string {
  return Number.isFinite(value) ? value.toFixed(digits) : "—";
}

function NodeDetail({ node }: { node: GraphNodeView }) {
  return (
    <div className="border-b border-border p-4" data-testid="graph-detail">
      <h2 className="text-[var(--text-base)] font-medium leading-snug text-ink">{node.title}</h2>
      <p className="mt-1 text-[var(--text-sm)] text-ink-2">
        {node.year ?? "年份未知"} · {ROLE_LABEL[node.role]}
      </p>
      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1.5 text-[var(--text-sm)]">
        <dt className="text-ink-2">入度</dt>
        <dd className="text-right text-ink">{node.inDegree}</dd>
        <dt className="text-ink-2">出度</dt>
        <dd className="text-right text-ink">{node.outDegree}</dd>
        <dt className="text-ink-2">PageRank</dt>
        <dd className="text-right text-ink">{metric(node.pagerank)}</dd>
        <dt className="text-ink-2">介数</dt>
        <dd className="text-right text-ink">{metric(node.betweenness)}</dd>
      </dl>
      {node.reason && <p className="mt-2 text-[var(--text-xs)] leading-relaxed text-ink-2">判定依据：{node.reason}</p>}
      <Link
        to={`/reader/${node.id}`}
        className="mt-3 inline-flex items-center gap-1.5 text-[var(--text-sm)] font-medium text-primary hover:underline"
      >
        在阅读器中打开
        <ExternalLink className="size-3.5" aria-hidden />
      </Link>
    </div>
  );
}

interface Props {
  graph: GraphView;
  selected: GraphNodeView | null;
  onSelect: (id: string) => void;
}

/** Right rail of 02 §4.5: node detail, rankings, and the later M5 tabs. */
export function GraphPanel({ graph, selected, onSelect }: Props) {
  const [tab, setTab] = useState<Tab>("metrics");
  const cornerstone = graph.nodes
    .filter((node) => node.role === "cornerstone")
    .sort((a, b) => b.pagerank - a.pagerank)
    .slice(0, 5);
  const peripheral = graph.nodes.filter((node) => node.role === "peripheral").sort((a, b) => b.pagerank - a.pagerank);
  const methods = new Map<string, number>();
  for (const edge of graph.edges) methods.set(edge.method, (methods.get(edge.method) ?? 0) + 1);
  const unmatched = graph.metrics["unmatched_references"];
  const isolated = graph.metrics["isolated"];
  const isolatedCount = Array.isArray(isolated) ? isolated.length : null;

  return (
    <aside className="flex w-[320px] shrink-0 flex-col border-l border-border bg-surface">
      {selected ? (
        <NodeDetail node={selected} />
      ) : (
        <div className="border-b border-border p-4">
          <EmptyState title="未选择节点" description="在画布中点击节点，或从指标榜选一个。" icon={<GitFork className="size-6" aria-hidden />} />
        </div>
      )}

      <div className="flex border-b border-border" role="tablist" aria-label="图谱面板">
        {TABS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            onClick={() => {
              setTab(key);
            }}
            className={cn(
              "flex-1 py-2 text-[var(--text-xs)]",
              tab === key ? "border-b-2 border-primary font-medium text-primary" : "text-ink-2 hover:text-ink",
            )}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="app-scroll flex-1 p-4">
        {tab === "metrics" && (
          <div className="space-y-4">
            <section>
              <h3 className="text-[var(--text-sm)] font-medium text-ink">基石 Top 5</h3>
              <p className="mt-0.5 text-[var(--text-xs)] text-ink-2">PageRank 前 20% 且入度 ≥ 2</p>
              {cornerstone.length === 0 ? (
                <p className="mt-2 text-[var(--text-xs)] text-ink-2">没有基石节点：所选文献之间的引用还不足以让任何一篇进入前 20%。</p>
              ) : (
                <ol className="mt-2 space-y-1.5">
                  {cornerstone.map((node, index) => (
                    <li key={node.id}>
                      <button
                        type="button"
                        data-testid="graph-metrics-row"
                        onClick={() => {
                          onSelect(node.id);
                        }}
                        className={cn(
                          "flex w-full items-baseline gap-2 rounded-control px-1 py-1 text-left text-[var(--text-sm)] hover:bg-surface-2",
                          selected?.id === node.id && "bg-surface-2",
                        )}
                      >
                        <span className="w-3 text-[var(--text-xs)] text-ink-2">{index + 1}</span>
                        <span className="min-w-0 flex-1 truncate text-ink">{node.title}</span>
                        <span className="text-[var(--text-xs)] text-ink-2">{metric(node.pagerank)}</span>
                      </button>
                    </li>
                  ))}
                </ol>
              )}
            </section>

            <section>
              <h3 className="text-[var(--text-sm)] font-medium text-ink">边缘论文</h3>
              <p className="mt-0.5 text-[var(--text-xs)] text-ink-2">入度 0、只引用他人</p>
              {peripheral.length === 0 ? (
                <p className="mt-2 text-[var(--text-xs)] text-ink-2">没有被引用为零的节点。</p>
              ) : (
                <ul className="mt-2 space-y-1.5">
                  {peripheral.map((node) => (
                    <li key={node.id}>
                      <button
                        type="button"
                        onClick={() => {
                          onSelect(node.id);
                        }}
                        className={cn(
                          "w-full truncate rounded-control px-1 py-1 text-left text-[var(--text-sm)] text-ink hover:bg-surface-2",
                          selected?.id === node.id && "bg-surface-2",
                        )}
                      >
                        {node.title}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section>
              <h3 className="text-[var(--text-sm)] font-medium text-ink">全部节点</h3>
              <p className="mt-0.5 text-[var(--text-xs)] text-ink-2">按 PageRank 排序</p>
              <ul className="mt-2 max-h-52 space-y-1 overflow-y-auto pr-1">
                {graph.nodes.map((node) => (
                  <li key={node.id}>
                    <button
                      type="button"
                      data-testid="graph-node-row"
                      onClick={() => {
                        onSelect(node.id);
                      }}
                      className={cn(
                        "flex w-full items-baseline gap-2 rounded-control px-1 py-1 text-left text-[var(--text-sm)] hover:bg-surface-2",
                        selected?.id === node.id && "bg-surface-2",
                      )}
                    >
                      <span className="min-w-0 flex-1 truncate text-ink">{node.title}</span>
                      <span className="shrink-0 text-[var(--text-xs)] text-ink-2">{ROLE_LABEL[node.role]}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>

            <section className="rounded-control border border-border bg-surface-2 p-3 text-[var(--text-xs)] text-ink-2">
              <p>
                节点 {graph.nodes.length} · 边 {graph.edges.length}
                {typeof unmatched === "number" && ` · 未匹配引用 ${String(unmatched)}`}
              </p>
              <p className="mt-1">
                匹配方式：
                {[...methods.entries()].map(([method, count]) => `${METHOD_LABEL[method] ?? method} ${String(count)}`).join(" · ") ||
                  "无"}
              </p>
              {isolatedCount !== null && isolatedCount > 0 && (
                <p className="mt-1" data-testid="graph-isolated">
                  未进入图的所选文献：{isolatedCount} 篇
                </p>
              )}
            </section>
          </div>
        )}

        {tab === "survey" && (
          <EmptyState
            title="综述尚未接入"
            description="T6.4 会基于图谱与 RAG 生成 400–800 字综述，每条论断带可点击的原文锚点。"
            icon={<Network className="size-6" aria-hidden />}
          />
        )}
        {tab === "future" && (
          <EmptyState
            title="Future Work 尚未接入"
            description="T6.5 会抽取未来工作方向，检索后续论文判定是否已被解决，证据不足一律标为未知。"
          />
        )}
      </div>
    </aside>
  );
}
