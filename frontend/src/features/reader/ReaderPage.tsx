import { ChevronRight, FileText, Image, Search, ZoomIn, ZoomOut } from "lucide-react";
import { useMemo, useState } from "react";

import { EmptyState } from "@/design/States";
import { cn } from "@/lib/cn";
import { mockBlocks, mockOutline, mockReferences, type OutlineItem } from "@/mocks/data";

function OutlineTree({
  items,
  activeId,
  onPick,
}: {
  items: OutlineItem[];
  activeId: string;
  onPick: (item: OutlineItem) => void;
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const visible = useMemo(() => {
    const out: OutlineItem[] = [];
    let skipLevel: number | null = null;
    for (const item of items) {
      if (skipLevel !== null) {
        if (item.level > skipLevel) continue;
        skipLevel = null;
      }
      out.push(item);
      if (collapsed.has(item.id)) skipLevel = item.level;
    }
    return out;
  }, [items, collapsed]);

  return (
    <ul className="flex flex-col">
      {visible.map((item) => {
        const hasChildren = items.some((other) => other.level > item.level && other.id !== item.id);
        return (
          <li key={item.id}>
            <div
              className={cn(
                "group flex items-center rounded-control pr-2 text-[var(--text-sm)]",
                activeId === item.id ? "bg-surface-2 text-primary" : "text-ink-2 hover:bg-surface-2",
              )}
              style={{ paddingLeft: `${(item.level - 1) * 12 + 4}px` }}
            >
              {hasChildren ? (
                <button
                  type="button"
                  aria-label={collapsed.has(item.id) ? "展开" : "折叠"}
                  onClick={() => {
                    setCollapsed((prev) => {
                      const next = new Set(prev);
                      if (next.has(item.id)) next.delete(item.id);
                      else next.add(item.id);
                      return next;
                    });
                  }}
                  className="flex size-5 shrink-0 items-center justify-center"
                >
                  <ChevronRight
                    className={cn("size-3.5 transition-transform", !collapsed.has(item.id) && "rotate-90")}
                    aria-hidden
                  />
                </button>
              ) : (
                <span className="size-5 shrink-0" />
              )}
              <button
                type="button"
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
      })}
    </ul>
  );
}

export function ReaderPage() {
  const [tab, setTab] = useState<"toc" | "thumbs">("toc");
  const [rightTab, setRightTab] = useState<"structure" | "qa" | "translate">("structure");
  const [activeSection, setActiveSection] = useState("s3");
  const [zoom, setZoom] = useState(100);
  const [page, setPage] = useState(3);

  return (
    <div className="flex h-full min-h-0">
      <aside className="flex w-[240px] shrink-0 flex-col border-r border-border bg-surface">
        <div className="flex border-b border-border" role="tablist" aria-label="左栏">
          {(["toc", "thumbs"] as const).map((key) => (
            <button
              key={key}
              role="tab"
              aria-selected={tab === key}
              onClick={() => {
                setTab(key);
              }}
              className={cn(
                "flex flex-1 items-center justify-center gap-1.5 py-2 text-[var(--text-sm)]",
                tab === key ? "border-b-2 border-primary font-medium text-primary" : "text-ink-2",
              )}
            >
              {key === "toc" ? <FileText className="size-3.5" aria-hidden /> : <Image className="size-3.5" aria-hidden />}
              {key === "toc" ? "目录" : "缩略图"}
            </button>
          ))}
        </div>
        <div className="app-scroll flex-1 p-2">
          {tab === "toc" ? (
            <OutlineTree
              items={mockOutline}
              activeId={activeSection}
              onPick={(item) => {
                setActiveSection(item.id);
                setPage(item.page);
              }}
            />
          ) : (
            <div className="grid grid-cols-2 gap-2">
              {Array.from({ length: 15 }, (_, i) => i + 1).map((n) => (
                <button
                  key={n}
                  type="button"
                  onClick={() => {
                    setPage(n);
                  }}
                  className={cn(
                    "flex aspect-[3/4] items-center justify-center rounded border text-[var(--text-xs)]",
                    page === n ? "border-primary text-primary" : "border-border text-ink-2 hover:border-primary",
                  )}
                >
                  {n}
                </button>
              ))}
            </div>
          )}
        </div>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col bg-surface-2">
        <div className="flex h-11 shrink-0 items-center gap-2 border-b border-border bg-surface px-3">
          <button
            type="button"
            aria-label="缩小"
            onClick={() => {
              setZoom((z) => Math.max(50, z - 10));
            }}
            className="rounded p-1.5 text-ink-2 hover:bg-surface-2 hover:text-ink"
          >
            <ZoomOut className="size-4" aria-hidden />
          </button>
          <span className="w-12 text-center text-[var(--text-sm)] text-ink-2">{zoom}%</span>
          <button
            type="button"
            aria-label="放大"
            onClick={() => {
              setZoom((z) => Math.min(300, z + 10));
            }}
            className="rounded p-1.5 text-ink-2 hover:bg-surface-2 hover:text-ink"
          >
            <ZoomIn className="size-4" aria-hidden />
          </button>
          <span className="mx-1 h-4 w-px bg-border" />
          <input
            type="number"
            value={page}
            min={1}
            max={15}
            aria-label="跳转页码"
            onChange={(event) => {
              setPage(Math.min(15, Math.max(1, Number(event.target.value) || 1)));
            }}
            className="h-7 w-14 rounded-control border border-border bg-surface px-2 text-center text-[var(--text-sm)]"
          />
          <span className="text-[var(--text-sm)] text-ink-2">/ 15</span>
          <div className="ml-auto flex items-center gap-1.5 rounded-control border border-border px-2 py-1">
            <Search className="size-3.5 text-ink-2" aria-hidden />
            <input
              placeholder="页内搜索"
              aria-label="页内搜索"
              className="w-32 bg-transparent text-[var(--text-sm)] outline-none placeholder:text-ink-2"
            />
          </div>
        </div>

        <div className="app-scroll flex-1 p-6">
          <div
            className="mx-auto max-w-[720px] rounded-card bg-surface p-10 shadow-sm"
            style={{ transform: `scale(${zoom / 100})`, transformOrigin: "top center" }}
          >
            <h2 className="text-[var(--text-lg)] font-semibold leading-snug">
              Attention Is All You Need
            </h2>
            <p className="mt-1 text-[var(--text-sm)] text-ink-2">
              Ashish Vaswani, Noam Shazeer, Niki Parmar, Jakob Uszkoreit, Llion Jones, Aidan N. Gomez,
              Łukasz Kaiser, Illia Polosukhin
            </p>
            <div className="mt-6 space-y-4">
              {mockBlocks
                .filter((block) => block.type === "paragraph")
                .map((block) => (
                  <p key={block.id} className="font-read text-[15px] leading-[1.75] text-ink">
                    {block.text}
                  </p>
                ))}
              {mockBlocks
                .filter((block) => block.type === "formula")
                .map((block) => (
                  <div
                    key={block.id}
                    className="rounded-control border border-border bg-surface-2 px-4 py-3 font-mono text-[var(--text-sm)] text-ink"
                  >
                    {block.latex}
                  </div>
                ))}
            </div>
          </div>
        </div>
      </section>

      <aside className="flex w-[320px] shrink-0 flex-col border-l border-border bg-surface">
        <div className="flex border-b border-border" role="tablist" aria-label="右栏">
          {(
            [
              ["structure", "结构"],
              ["qa", "问答"],
              ["translate", "翻译"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              role="tab"
              aria-selected={rightTab === key}
              onClick={() => {
                setRightTab(key);
              }}
              className={cn(
                "flex-1 py-2 text-[var(--text-sm)]",
                rightTab === key ? "border-b-2 border-primary font-medium text-primary" : "text-ink-2",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="app-scroll flex-1 p-4">
          {rightTab === "structure" && (
            <div className="space-y-4">
              <section>
                <h3 className="mb-2 text-[var(--text-sm)] font-medium text-ink">参考文献</h3>
                <ul className="space-y-2">
                  {mockReferences.map((ref) => (
                    <li key={ref.id} className="rounded-control border border-border p-2">
                      <p className="text-[var(--text-xs)] text-ink-2">[{ref.index}]</p>
                      <p className="line-clamp-2 text-[var(--text-sm)] text-ink">{ref.title ?? ref.raw}</p>
                      <div className="mt-1 flex items-center gap-2">
                        <div className="h-1 flex-1 overflow-hidden rounded-full bg-surface-2">
                          <div
                            className="h-full rounded-full bg-accent"
                            style={{ width: `${String(ref.worth_score ?? 0)}%` }}
                          />
                        </div>
                        <span className="text-[var(--text-xs)] text-ink-2">{ref.worth_score ?? 0}</span>
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
            </div>
          )}
          {rightTab === "qa" && (
            <EmptyState title="就这篇文献提问" description="回答中的每条结论都会附原文锚点。" />
          )}
          {rightTab === "translate" && (
            <EmptyState title="尚未翻译" description="整篇翻译后可在此下载 Markdown 或 HTML。" />
          )}
        </div>
      </aside>
    </div>
  );
}
