import { ChevronRight, Search } from "lucide-react";
import { useMemo, useState } from "react";

import { cn } from "@/lib/cn";
import type { OutlineItem } from "./api";

/**
 * The collapsible heading tree (02 §4.2).
 *
 * A 541-page book has ~1 000 headings, so two things matter here: filtering
 * by title, and not rendering 1 000 rows at once. A filter shows matches flat
 * (their nesting is meaningless once most parents are hidden); without one,
 * the tree renders only expanded branches.
 */
export function OutlinePanel({
  items,
  activeId,
  onPick,
}: {
  items: OutlineItem[];
  activeId: string | null;
  onPick: (item: OutlineItem) => void;
}) {
  const [query, setQuery] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return null;
    return items.filter((item) => item.title.toLowerCase().includes(needle));
  }, [items, query]);

  const visible = useMemo(() => (matches ? matches : visibleTree(items, collapsed)), [items, matches, collapsed]);

  if (items.length === 0) {
    return (
      <p className="px-2 py-6 text-center text-[var(--text-sm)] text-ink-2">
        这份 PDF 没有可用的标题结构。
      </p>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-1.5 border-b border-border px-2 py-1.5">
        <Search className="size-3.5 shrink-0 text-ink-2" aria-hidden />
        <input
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
          }}
          placeholder="过滤标题"
          aria-label="过滤标题"
          className="min-w-0 flex-1 bg-transparent text-[var(--text-sm)] outline-none placeholder:text-ink-2"
        />
        {query && (
          <span className="shrink-0 text-[var(--text-xs)] text-ink-2">{matches?.length ?? 0} 条</span>
        )}
      </div>
      <div className="app-scroll flex-1 py-1">
        {visible.length === 0 ? (
          <p className="px-2 py-6 text-center text-[var(--text-sm)] text-ink-2">没有匹配的标题。</p>
        ) : (
          <ul className="flex flex-col">
            {visible.map((item) => (
              <OutlineRow
                key={item.id}
                item={item}
                active={activeId === item.id}
                hasChildren={!matches && hasChild(items, item)}
                collapsed={collapsed.has(item.id)}
                flat={Boolean(matches)}
                onToggle={() => {
                  setCollapsed((prev) => {
                    const next = new Set(prev);
                    if (next.has(item.id)) next.delete(item.id);
                    else next.add(item.id);
                    return next;
                  });
                }}
                onPick={onPick}
              />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function OutlineRow({
  item,
  active,
  hasChildren,
  collapsed,
  flat,
  onToggle,
  onPick,
}: {
  item: OutlineItem;
  active: boolean;
  hasChildren: boolean;
  collapsed: boolean;
  flat: boolean;
  onToggle: () => void;
  onPick: (item: OutlineItem) => void;
}) {
  return (
    <li>
      <div
        className={cn(
          "group flex items-center rounded-control pr-2 text-[var(--text-sm)]",
          active ? "bg-surface-2 text-primary" : "text-ink-2 hover:bg-surface-2",
        )}
        style={{ paddingLeft: `${(flat ? 1 : item.level) * 12}px` }}
      >
        {hasChildren ? (
          <button
            type="button"
            aria-label={collapsed ? "展开" : "折叠"}
            aria-expanded={!collapsed}
            onClick={onToggle}
            className="flex size-5 shrink-0 items-center justify-center"
          >
            <ChevronRight
              className={cn("size-3.5 transition-transform duration-[--dur-fast]", !collapsed && "rotate-90")}
              aria-hidden
            />
          </button>
        ) : (
          <span className="size-5 shrink-0" />
        )}
        <button
          type="button"
          data-outline-id={item.id}
          onClick={() => {
            onPick(item);
          }}
          className="flex min-w-0 flex-1 items-center gap-2 py-1.5 text-left"
        >
          <span className="truncate">{item.title}</span>
          <span className="ml-auto shrink-0 text-[var(--text-xs)] text-ink-2">{item.page}</span>
        </button>
      </div>
    </li>
  );
}

/** The rows shown when nothing is collapsed: a heading and its subtree. */
function visibleTree(items: OutlineItem[], collapsed: Set<string>): OutlineItem[] {
  const out: OutlineItem[] = [];
  let skipBelow: number | null = null;
  for (const item of items) {
    if (skipBelow !== null) {
      if (item.level > skipBelow) continue;
      skipBelow = null;
    }
    out.push(item);
    if (collapsed.has(item.id)) skipBelow = item.level;
  }
  return out;
}

/** Whether the next heading is deeper than this one. */
function hasChild(items: OutlineItem[], item: OutlineItem): boolean {
  const index = items.indexOf(item);
  const next = items[index + 1];
  return next !== undefined && next.level > item.level;
}
