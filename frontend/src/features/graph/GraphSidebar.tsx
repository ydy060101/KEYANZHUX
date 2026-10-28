import { Download, ImageDown } from "lucide-react";

import { Button } from "@/design/Button";
import { ROLE_LABEL, ROLE_ORDER, type GraphLayout, type GraphRole } from "@/features/graph/api";
import { cn } from "@/lib/cn";

const ROLE_DOT: Record<GraphRole, string> = {
  cornerstone: "bg-primary",
  middle: "bg-ink-2",
  peripheral: "bg-accent",
};

interface Props {
  roles: Set<GraphRole>;
  onToggleRole: (role: GraphRole) => void;
  yearBounds: { min: number; max: number } | null;
  minYear: number | null;
  onMinYear: (value: number | null) => void;
  minInDegree: number;
  onMinInDegree: (value: number) => void;
  layout: GraphLayout;
  onLayout: (value: GraphLayout) => void;
  nodeCount: number;
  hiddenCount: number;
  canExport: boolean;
  onExportPng: () => void;
  onExportJson: () => void;
}

/** Left rail of 02 §4.5: role, year and in-degree filters, legend, export. */
export function GraphSidebar(props: Props) {
  const bounds = props.yearBounds;
  return (
    <aside className="flex w-[214px] shrink-0 flex-col gap-4 overflow-y-auto border-r border-border bg-surface p-3">
      <section>
        <h2 className="text-[var(--text-sm)] font-medium text-ink">按角色</h2>
        <div className="mt-2 space-y-1.5">
          {ROLE_ORDER.map((role) => (
            <label key={role} className="flex cursor-pointer items-center gap-2 text-[var(--text-sm)] text-ink-2">
              <input
                type="checkbox"
                className="size-3.5 accent-[var(--primary)]"
                checked={props.roles.has(role)}
                onChange={() => {
                  props.onToggleRole(role);
                }}
                data-testid={`graph-role-${role}`}
              />
              <span className={cn("size-2.5 rounded-full", ROLE_DOT[role])} aria-hidden />
              {ROLE_LABEL[role]}
            </label>
          ))}
        </div>
      </section>

      <section>
        <h2 className="text-[var(--text-sm)] font-medium text-ink">年份</h2>
        {bounds ? (
          <div className="mt-2 space-y-1.5">
            <input
              type="range"
              min={bounds.min}
              max={bounds.max}
              value={props.minYear ?? bounds.min}
              onChange={(event) => {
                const value = Number(event.target.value);
                props.onMinYear(value <= bounds.min ? null : value);
              }}
              aria-label="最早年份"
              className="w-full accent-[var(--primary)]"
              data-testid="graph-year"
            />
            <div className="flex items-center justify-between text-[var(--text-xs)] text-ink-2">
              <span>{props.minYear === null ? "不限" : `≥ ${String(props.minYear)}`}</span>
              {props.minYear !== null && (
                <button
                  type="button"
                  className="text-primary hover:underline"
                  onClick={() => {
                    props.onMinYear(null);
                  }}
                >
                  重置
                </button>
              )}
            </div>
            <p className="text-[var(--text-xs)] text-ink-2">无年份的节点始终显示。</p>
          </div>
        ) : (
          <p className="mt-2 text-[var(--text-xs)] text-ink-2">所选文献没有年份信息。</p>
        )}
      </section>

      <section>
        <h2 className="text-[var(--text-sm)] font-medium text-ink">最小入度</h2>
        <input
          type="number"
          min={0}
          max={99}
          value={props.minInDegree}
          onChange={(event) => {
            props.onMinInDegree(Math.max(0, Number(event.target.value) || 0));
          }}
          aria-label="最小入度"
          data-testid="graph-indegree"
          className="mt-2 h-8 w-full rounded-control border border-border bg-surface px-2 text-[var(--text-sm)] text-ink outline-none focus-visible:border-primary"
        />
      </section>

      <section>
        <h2 className="text-[var(--text-sm)] font-medium text-ink">布局</h2>
        <div className="mt-2 grid grid-cols-2 gap-1 rounded-control bg-surface-2 p-1" data-testid="graph-layout">
          {(
            [
              ["force", "力导向"],
              ["timeline", "时间轴"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              aria-pressed={props.layout === key}
              onClick={() => {
                props.onLayout(key);
              }}
              className={cn(
                "rounded-[6px] px-2 py-1 text-[var(--text-xs)] transition-colors",
                props.layout === key ? "bg-surface font-medium text-ink shadow-sm" : "text-ink-2 hover:text-ink",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </section>

      <p className="text-[var(--text-xs)] text-ink-2" data-testid="graph-visible-count">
        显示 {props.nodeCount - props.hiddenCount} / {props.nodeCount} 个节点
      </p>

      <section className="mt-auto space-y-2">
        <h2 className="text-[var(--text-sm)] font-medium text-ink">图例</h2>
        <div className="space-y-1">
          {ROLE_ORDER.map((role) => (
            <div key={role} className="flex items-center gap-2 text-[var(--text-xs)] text-ink-2">
              <span className={cn("size-2.5 rounded-full", ROLE_DOT[role])} aria-hidden />
              {ROLE_LABEL[role]}
            </div>
          ))}
        </div>
        <Button
          size="sm"
          variant="secondary"
          className="w-full"
          disabled={!props.canExport}
          onClick={props.onExportPng}
          data-testid="graph-export-png"
        >
          <ImageDown className="size-4" aria-hidden />
          导出 PNG
        </Button>
        <Button size="sm" variant="secondary" className="w-full" onClick={props.onExportJson} data-testid="graph-export-json">
          <Download className="size-4" aria-hidden />
          导出 JSON
        </Button>
      </section>
    </aside>
  );
}
