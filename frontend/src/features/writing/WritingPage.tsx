import { lazy, Suspense, useState } from "react";

import { Skeleton } from "@/design/States";
import { cn } from "@/lib/cn";
import { OutlineWorkspace } from "./OutlineWorkspace";
import { TranslateWorkspace } from "./TranslateWorkspace";

// Monaco + Mermaid and ECharts are only needed once their tab is opened.
const FigureWorkspace = lazy(() =>
  import("./FigureWorkspace").then((module) => ({ default: module.FigureWorkspace })),
);
const DataWorkspace = lazy(() => import("./DataWorkspace").then((module) => ({ default: module.DataWorkspace })));

type Workspace = "outline" | "figures" | "data" | "translate";

const TABS: { key: Workspace; label: string; hint: string }[] = [
  { key: "outline", label: "论文框架", hint: "想法 → 框架 → 真实参考文献" },
  { key: "figures", label: "图表工坊", hint: "脚本、沙箱渲染与修复" },
  { key: "data", label: "数据工坊", hint: "CSV → 图表与可核对图注" },
  { key: "translate", label: "学术翻译", hint: "中文摘要 → 学术英文" },
];

/**
 * `/writing` — the writing studio (02 §4.6, T7.5).
 *
 * All four workspaces talk to their real endpoints; there is no sample
 * reference list or placeholder draft. Each workspace is mounted on first
 * visit and then hidden rather than unmounted, so switching tabs does not
 * discard an uploaded CSV or a generated script.
 */
export function WritingPage() {
  const [workspace, setWorkspace] = useState<Workspace>("outline");
  const [visited, setVisited] = useState<Set<Workspace>>(new Set(["outline"]));

  const open = (next: Workspace) => {
    setWorkspace(next);
    setVisited((current) => {
      if (current.has(next)) return current;
      const updated = new Set(current);
      updated.add(next);
      return updated;
    });
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center gap-1 border-b border-border bg-surface px-4" role="tablist" aria-label="写作工坊">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            id={`writing-tab-${tab.key}`}
            type="button"
            role="tab"
            aria-selected={workspace === tab.key}
            aria-controls={`writing-panel-${tab.key}`}
            data-testid={`writing-tab-${tab.key}`}
            title={tab.hint}
            onClick={() => {
              open(tab.key);
            }}
            className={cn(
              "px-3 py-3 text-[var(--text-base)] transition-colors duration-[--dur-fast]",
              workspace === tab.key
                ? "border-b-2 border-primary font-medium text-primary"
                : "border-b-2 border-transparent text-ink-2 hover:text-ink",
            )}
          >
            {tab.label}
          </button>
        ))}
        <span className="ml-auto hidden text-[var(--text-xs)] text-ink-2 xl:block">
          {TABS.find((tab) => tab.key === workspace)?.hint}
        </span>
      </div>

      <div className="flex min-h-0 flex-1">
        {TABS.map((tab) => (
          <div
            key={tab.key}
            id={`writing-panel-${tab.key}`}
            role="tabpanel"
            aria-labelledby={`writing-tab-${tab.key}`}
            hidden={workspace !== tab.key}
            className={cn("min-h-0 flex-1", workspace === tab.key ? "flex" : "hidden")}
          >
            {visited.has(tab.key) && (
              <Suspense
                fallback={
                  <div className="flex flex-1 flex-col gap-3 p-6" aria-busy>
                    <Skeleton className="h-8 w-48" />
                    <Skeleton className="flex-1" />
                  </div>
                }
              >
                {tab.key === "outline" ? (
                  <OutlineWorkspace />
                ) : tab.key === "figures" ? (
                  <FigureWorkspace />
                ) : tab.key === "data" ? (
                  <DataWorkspace active={workspace === "data"} />
                ) : (
                  <TranslateWorkspace />
                )}
              </Suspense>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
