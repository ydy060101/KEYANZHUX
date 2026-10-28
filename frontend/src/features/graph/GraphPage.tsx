import { useQuery } from "@tanstack/react-query";
import type cytoscape from "cytoscape";
import { GitFork, Plus } from "lucide-react";
import { useCallback, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { EmptyState, ErrorState, Skeleton } from "@/design/States";
import { fetchGraph, graphKeys, ROLE_ORDER, type GraphLayout, type GraphRole } from "@/features/graph/api";
import { CytoscapeGraph } from "@/features/graph/CytoscapeGraph";
import { GraphPanel } from "@/features/graph/GraphPanel";
import { GraphSelection } from "@/features/graph/GraphSelection";
import { GraphSidebar } from "@/features/graph/GraphSidebar";

function readSurface(): string {
  if (typeof document === "undefined") return "#ffffff";
  return getComputedStyle(document.documentElement).getPropertyValue("--surface").trim() || "#ffffff";
}

function download(name: string, href: string, revoke = false): void {
  const link = document.createElement("a");
  link.href = href;
  link.download = name;
  link.click();
  if (revoke) window.setTimeout(() => URL.revokeObjectURL(href), 1000);
}

export function GraphPage() {
  const { graphId } = useParams<{ graphId: string }>();
  return graphId ? <GraphWorkspace graphId={graphId} /> : <GraphSelection />;
}

function GraphWorkspace({ graphId }: { graphId: string }) {
  const query = useQuery({
    queryKey: graphKeys.detail(graphId),
    queryFn: () => fetchGraph(graphId),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [roles, setRoles] = useState<Set<GraphRole>>(new Set(ROLE_ORDER));
  const [minYear, setMinYear] = useState<number | null>(null);
  const [minInDegree, setMinInDegree] = useState(0);
  const [layout, setLayout] = useState<GraphLayout>("force");
  const core = useRef<cytoscape.Core | null>(null);
  const onCore = useCallback((value: cytoscape.Core | null) => {
    core.current = value;
  }, []);

  const graph = query.data;
  const nodes = useMemo(() => graph?.nodes ?? [], [graph]);
  const years = nodes.map((node) => node.year).filter((year): year is number => year !== null);
  const yearBounds = years.length > 0 ? { min: Math.min(...years), max: Math.max(...years) } : null;

  const visibleIds = useMemo(() => {
    const ids = new Set<string>();
    for (const node of nodes) {
      if (!roles.has(node.role)) continue;
      if (minYear !== null && node.year !== null && node.year < minYear) continue;
      if (node.inDegree < minInDegree) continue;
      ids.add(node.id);
    }
    return ids;
  }, [nodes, roles, minYear, minInDegree]);

  const selected = nodes.find((node) => node.id === selectedId) ?? null;
  const onSelect = useCallback((id: string | null) => {
    setSelectedId(id);
  }, []);

  const toggleRole = (role: GraphRole) => {
    setRoles((current) => {
      const next = new Set(current);
      if (next.has(role)) next.delete(role);
      else next.add(role);
      return next;
    });
  };

  const exportJson = () => {
    if (!graph) return;
    const blob = new Blob([JSON.stringify(graph, null, 2)], { type: "application/json" });
    download(`graph-${graph.id.slice(0, 8)}.json`, URL.createObjectURL(blob), true);
  };

  const exportPng = () => {
    if (!core.current || !graph) return;
    download(`graph-${graph.id.slice(0, 8)}.png`, core.current.png({ full: true, scale: 2, bg: readSurface() }));
  };

  if (query.isPending) {
    return (
      <div className="flex h-full min-h-0 flex-col gap-3 p-6" aria-busy>
        <Skeleton className="h-8 w-52" />
        <Skeleton className="flex-1" />
      </div>
    );
  }

  if (query.isError || !graph) {
    return (
      <div className="flex h-full items-center justify-center">
        <ErrorState
          message="图谱加载失败"
          detail={query.error instanceof Error ? query.error.message : undefined}
          onRetry={() => {
            void query.refetch();
          }}
        />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border px-4">
        <h1 className="text-[var(--text-base)] font-medium text-ink">引用图谱</h1>
        <span className="text-[var(--text-xs)] text-ink-2" data-testid="graph-summary">
          {graph.nodes.length} 节点 · {graph.edges.length} 边
        </span>
        <Link
          to="/graph"
          className="ml-auto inline-flex items-center gap-1 text-[var(--text-sm)] font-medium text-primary hover:underline"
        >
          <Plus className="size-3.5" aria-hidden />
          新建图谱
        </Link>
      </header>

      <div className="flex min-h-0 flex-1">
        <GraphSidebar
          roles={roles}
          onToggleRole={toggleRole}
          yearBounds={yearBounds}
          minYear={minYear}
          onMinYear={setMinYear}
          minInDegree={minInDegree}
          onMinInDegree={setMinInDegree}
          layout={layout}
          onLayout={setLayout}
          nodeCount={graph.nodes.length}
          hiddenCount={graph.nodes.length - visibleIds.size}
          canExport={graph.nodes.length > 0}
          onExportPng={exportPng}
          onExportJson={exportJson}
        />

        <section className="relative min-w-0 flex-1 bg-surface-2">
          {graph.nodes.length > 0 ? (
            <CytoscapeGraph
              graph={graph}
              selectedId={selectedId}
              visibleIds={visibleIds}
              layout={layout}
              onSelect={onSelect}
              onCore={onCore}
            />
          ) : (
            <div className="flex h-full items-center justify-center">
              <EmptyState
                title="所选文献之间没有可匹配的引用"
                description={`匹配按 DOI → arXiv ID → 标题（≥ 0.92 且年份一致）进行；未匹配的参考文献不进入图。${typeof graph.metrics["unmatched_references"] === "number" ? `本次有 ${String(graph.metrics["unmatched_references"])} 条参考文献未匹配到所选文献。` : ""}`}
                icon={<GitFork className="size-6" aria-hidden />}
                action={
                  <Link to="/graph" className="text-[var(--text-sm)] font-medium text-primary hover:underline">
                    换一组文献
                  </Link>
                }
              />
            </div>
          )}
          {graph.nodes.length > 0 && visibleIds.size === 0 && (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <p className="rounded-card border border-border bg-surface px-4 py-3 text-[var(--text-sm)] text-ink-2 shadow-sm">
                当前筛选没有匹配的节点，放宽条件试试。
              </p>
            </div>
          )}
        </section>

        <GraphPanel graph={graph} selected={selected} onSelect={setSelectedId} />
      </div>
    </div>
  );
}
