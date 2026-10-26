import { Download, GitFork } from "lucide-react";
import { useState } from "react";

import { Button } from "@/design/Button";
import { EmptyState } from "@/design/States";
import { cn } from "@/lib/cn";

interface Node {
  id: string;
  label: string;
  year: number;
  role: "cornerstone" | "middle" | "peripheral";
  pagerank: number;
  inDegree: number;
  x: number;
  y: number;
}

const NODES: Node[] = [
  { id: "n1", label: "Attention Is All You Need", year: 2017, role: "cornerstone", pagerank: 0.31, inDegree: 9, x: 50, y: 42 },
  { id: "n2", label: "BERT", year: 2018, role: "cornerstone", pagerank: 0.24, inDegree: 7, x: 34, y: 30 },
  { id: "n3", label: "GPT-3", year: 2020, role: "cornerstone", pagerank: 0.18, inDegree: 6, x: 68, y: 24 },
  { id: "n4", label: "RoBERTa", year: 2019, role: "middle", pagerank: 0.09, inDegree: 3, x: 26, y: 62 },
  { id: "n5", label: "T5", year: 2019, role: "middle", pagerank: 0.07, inDegree: 2, x: 62, y: 58 },
  { id: "n6", label: "LLaMA", year: 2023, role: "peripheral", pagerank: 0.04, inDegree: 1, x: 78, y: 74 },
  { id: "n7", label: "Chinchilla", year: 2022, role: "peripheral", pagerank: 0.04, inDegree: 1, x: 44, y: 78 },
  { id: "n8", label: "FlashAttention", year: 2022, role: "peripheral", pagerank: 0.03, inDegree: 1, x: 20, y: 46 },
];

const EDGES: [string, string][] = [
  ["n2", "n1"],
  ["n3", "n1"],
  ["n4", "n2"],
  ["n5", "n1"],
  ["n6", "n3"],
  ["n7", "n3"],
  ["n8", "n1"],
  ["n3", "n2"],
  ["n4", "n5"],
];

const ROLE_STYLE: Record<Node["role"], string> = {
  cornerstone: "bg-primary text-white",
  middle: "bg-ink-2 text-white",
  peripheral: "bg-accent text-white",
};

const ROLE_LABEL: Record<Node["role"], string> = {
  cornerstone: "基石",
  middle: "中间",
  peripheral: "边缘",
};

export function GraphPage() {
  const [selected, setSelected] = useState<Node | null>(NODES[0] ?? null);
  const [tab, setTab] = useState<"survey" | "future" | "metrics">("metrics");

  const byId = new Map(NODES.map((node) => [node.id, node]));

  return (
    <div className="flex h-full min-h-0">
      <aside className="flex w-[200px] shrink-0 flex-col gap-3 border-r border-border bg-surface p-3">
        <h2 className="text-[var(--text-sm)] font-medium text-ink">筛选</h2>
        {(["cornerstone", "middle", "peripheral"] as const).map((role) => (
          <label key={role} className="flex items-center gap-2 text-[var(--text-sm)] text-ink-2">
            <input type="checkbox" defaultChecked />
            {ROLE_LABEL[role]}
          </label>
        ))}
        <div className="mt-2 space-y-1">
          <p className="text-[var(--text-sm)] text-ink-2">年份</p>
          <input type="range" min={2017} max={2023} defaultValue={2017} className="w-full" aria-label="起始年份" />
        </div>
        <div className="mt-auto flex flex-col gap-2">
          <Button size="sm" variant="secondary">
            <Download className="size-4" aria-hidden />
            导出 PNG
          </Button>
          <Button size="sm" variant="secondary">
            <Download className="size-4" aria-hidden />
            导出 JSON
          </Button>
        </div>
      </aside>

      <section className="relative min-w-0 flex-1 bg-surface-2">
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="h-full w-full" role="img" aria-label="引用关系图">
          {EDGES.map(([from, to]) => {
            const a = byId.get(from);
            const b = byId.get(to);
            if (!a || !b) return null;
            return (
              <line
                key={`${from}-${to}`}
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke="var(--border)"
                strokeWidth={0.4}
                markerEnd="url(#arrow)"
              />
            );
          })}
          <defs>
            <marker id="arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
              <path d="M0,0 L6,3 L0,6 z" fill="var(--border)" />
            </marker>
          </defs>
        </svg>
        {NODES.map((node) => (
          <button
            key={node.id}
            type="button"
            onClick={() => {
              setSelected(node);
            }}
            style={{
              left: `${String(node.x)}%`,
              top: `${String(node.y)}%`,
              width: `${String(60 + node.inDegree * 8)}px`,
              height: `${String(60 + node.inDegree * 8)}px`,
            }}
            className={cn(
              "absolute flex -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full p-2 text-center text-[10px] leading-tight transition-transform hover:scale-105",
              ROLE_STYLE[node.role],
              selected?.id === node.id && "ring-2 ring-primary ring-offset-2 ring-offset-surface-2",
            )}
            title={`${node.label} (${String(node.year)})`}
          >
            <span className="line-clamp-2">{node.label}</span>
          </button>
        ))}
        <div className="absolute bottom-3 left-3 flex gap-3 rounded-control border border-border bg-surface px-3 py-1.5 text-[var(--text-xs)] text-ink-2">
          {(["cornerstone", "middle", "peripheral"] as const).map((role) => (
            <span key={role} className="flex items-center gap-1.5">
              <span className={cn("size-2.5 rounded-full", ROLE_STYLE[role])} />
              {ROLE_LABEL[role]}
            </span>
          ))}
        </div>
      </section>

      <aside className="flex w-[320px] shrink-0 flex-col border-l border-border bg-surface">
        {selected ? (
          <div className="border-b border-border p-4">
            <h3 className="text-[var(--text-base)] font-medium leading-snug text-ink">{selected.label}</h3>
            <p className="mt-1 text-[var(--text-sm)] text-ink-2">
              {selected.year} · {ROLE_LABEL[selected.role]}
            </p>
            <dl className="mt-2 grid grid-cols-2 gap-1 text-[var(--text-sm)]">
              <dt className="text-ink-2">入度</dt>
              <dd className="text-ink">{selected.inDegree}</dd>
              <dt className="text-ink-2">PageRank</dt>
              <dd className="text-ink">{selected.pagerank.toFixed(2)}</dd>
            </dl>
            <Button size="sm" variant="secondary" className="mt-3 w-full">
              在阅读器中打开
            </Button>
          </div>
        ) : (
          <div className="border-b border-border p-4">
            <EmptyState title="未选择节点" description="点击图中节点查看详情。" icon={<GitFork className="size-6" aria-hidden />} />
          </div>
        )}

        <div className="flex border-b border-border" role="tablist" aria-label="图谱面板">
          {(
            [
              ["survey", "综述"],
              ["future", "Future Work"],
              ["metrics", "指标榜"],
            ] as const
          ).map(([key, label]) => (
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
                tab === key ? "border-b-2 border-primary font-medium text-primary" : "text-ink-2",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="app-scroll flex-1 p-4">
          {tab === "metrics" && (
            <ol className="space-y-2">
              {[...NODES]
                .sort((a, b) => b.pagerank - a.pagerank)
                .slice(0, 5)
                .map((node, index) => (
                  <li key={node.id} className="flex items-center gap-2 text-[var(--text-sm)]">
                    <span className="w-4 text-ink-2">{index + 1}</span>
                    <span className="min-w-0 flex-1 truncate text-ink">{node.label}</span>
                    <span className="text-ink-2">{node.pagerank.toFixed(2)}</span>
                  </li>
                ))}
            </ol>
          )}
          {tab === "survey" && <EmptyState title="尚未生成综述" description="基于图谱生成 400–800 字综述，每条论断可溯源。" />}
          {tab === "future" && <EmptyState title="尚未分析" description="抽取未来工作方向，并判定是否已被后续论文解决。" />}
        </div>
      </aside>
    </div>
  );
}
