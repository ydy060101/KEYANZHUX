import { Maximize2, Moon, Search, Sun, ZoomIn, ZoomOut } from "lucide-react";
import { useEffect, useState } from "react";

import { useTheme } from "@/design/theme";
import { cn } from "@/lib/cn";

/** The reader's top bar: zoom, fit-to-width, page box, search, theme (02 §4.2). */
export function Toolbar({
  page,
  total,
  zoom,
  fitWidth,
  onZoom,
  onFitWidth,
  onPage,
  fileHref,
}: {
  page: number;
  total: number;
  zoom: number;
  fitWidth: boolean;
  onZoom: (zoom: number) => void;
  onFitWidth: (fit: boolean) => void;
  onPage: (page: number) => void;
  fileHref: string;
}) {
  const [draft, setDraft] = useState(String(page));
  useEffect(() => {
    setDraft(String(page));
  }, [page]);

  const { resolved, setMode } = useTheme();
  const dark = resolved === "dark";

  return (
    <div className="flex h-11 shrink-0 items-center gap-1.5 overflow-x-auto border-b border-border bg-surface px-3">
      <button
        type="button"
        aria-label="缩小"
        onClick={() => {
          onZoom(zoom - 10);
        }}
        className="shrink-0 rounded p-1.5 text-ink-2 hover:bg-surface-2 hover:text-ink"
      >
        <ZoomOut className="size-4" aria-hidden />
      </button>
      <span className="w-12 shrink-0 text-center text-[var(--text-sm)] text-ink-2">{zoom}%</span>
      <button
        type="button"
        aria-label="放大"
        onClick={() => {
          onZoom(zoom + 10);
        }}
        className="shrink-0 rounded p-1.5 text-ink-2 hover:bg-surface-2 hover:text-ink"
      >
        <ZoomIn className="size-4" aria-hidden />
      </button>
      <button
        type="button"
        aria-pressed={fitWidth}
        aria-label="适应宽度"
        onClick={() => {
          onFitWidth(!fitWidth);
        }}
        className={cn(
          "shrink-0 whitespace-nowrap rounded px-2 py-1 text-[var(--text-xs)]",
          fitWidth ? "bg-surface-2 font-medium text-primary" : "text-ink-2 hover:bg-surface-2 hover:text-ink",
        )}
      >
        适应宽度
      </button>
      <span className="mx-1 h-4 w-px shrink-0 bg-border" />
      <input
        value={draft}
        inputMode="numeric"
        aria-label="跳转页码"
        onChange={(event) => {
          setDraft(event.target.value.replace(/\D/g, ""));
        }}
        onKeyDown={(event) => {
          if (event.key !== "Enter") return;
          onPage(Number(draft) || 1);
        }}
        onBlur={() => {
          onPage(Number(draft) || 1);
        }}
        className="h-7 w-14 shrink-0 rounded-control border border-border bg-surface px-2 text-center text-[var(--text-sm)]"
      />
      <span className="shrink-0 whitespace-nowrap text-[var(--text-sm)] text-ink-2">/ {total}</span>
      <div className="ml-auto flex shrink-0 items-center gap-1.5 rounded-control border border-border px-2 py-1">
        <Search className="size-3.5 text-ink-2" aria-hidden />
        <input
          placeholder="页内搜索"
          aria-label="页内搜索"
          className="w-28 bg-transparent text-[var(--text-sm)] outline-none placeholder:text-ink-2"
        />
      </div>
      <button
        type="button"
        aria-label={dark ? "切换到浅色主题" : "切换到深色主题"}
        onClick={() => {
          setMode(dark ? "light" : "dark");
        }}
        className="shrink-0 rounded p-1.5 text-ink-2 hover:bg-surface-2 hover:text-ink"
      >
        {dark ? <Sun className="size-4" aria-hidden /> : <Moon className="size-4" aria-hidden />}
      </button>
      <a
        href={fileHref}
        target="_blank"
        rel="noreferrer"
        aria-label="在新窗口打开 PDF"
        className="shrink-0 rounded p-1.5 text-ink-2 hover:bg-surface-2 hover:text-ink"
      >
        <Maximize2 className="size-4" aria-hidden />
      </a>
    </div>
  );
}

/** The left rail's thumbnail grid: one numbered tile per page. */
export function Thumbnails({
  total,
  current,
  onPick,
}: {
  total: number;
  current: number;
  onPick: (page: number) => void;
}) {
  return (
    <div className="app-scroll grid grid-cols-2 gap-2 p-2">
      {Array.from({ length: total }, (_, index) => index + 1).map((number) => (
        <button
          key={number}
          type="button"
          onClick={() => {
            onPick(number);
          }}
          className={cn(
            "flex aspect-[3/4] items-center justify-center rounded-control border text-[var(--text-xs)]",
            current === number ? "border-primary text-primary" : "border-border text-ink-2 hover:border-primary",
          )}
        >
          {number}
        </button>
      ))}
    </div>
  );
}
