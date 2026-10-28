import { useQuery } from "@tanstack/react-query";
import { Languages, Minus, Plus, X } from "lucide-react";
import { useCallback, useMemo, useRef, useState, type RefObject } from "react";

import { ErrorState, Skeleton } from "@/design/States";
import { cn } from "@/lib/cn";
import { scaleFor } from "./pdf";
import type { Direction, TranslationBlock } from "./translateApi";
import { fetchTranslation } from "./translateApi";
import { useLinkedScroll } from "./useBilingualSync";

const LABEL: Record<Direction, string> = { en2zh: "英 → 中", zh2en: "中 → 英" };
const MIN_FONT = 13;
const MAX_FONT = 20;
const DEFAULT_FONT = 15;

export interface BilingualPaneProps {
  docId: string;
  direction: Direction;
  onDirection: (direction: Direction) => void;
  /** The PDF column's scroll container. */
  pdfScrollRef: RefObject<HTMLDivElement | null>;
  /** Page boxes by page number, registered by `PageView`. */
  pageNodes: RefObject<Map<number, HTMLDivElement>>;
  zoom: number;
  onClose: () => void;
  onOpenTranslateTab: () => void;
}

/**
 * The translation half of the bilingual reader (02 §4.2, T4.3).
 *
 * The left half is the real PDF. Scrolling either column selects a block from
 * that column's geometry — the block crossing the reading line — and brings
 * the matching block in the other column into view. The linkage lives in
 * `useBilingualSync`; this file draws the pane.
 */
export function BilingualPane({
  docId,
  direction,
  onDirection,
  pdfScrollRef,
  pageNodes,
  zoom,
  onClose,
  onOpenTranslateTab,
}: BilingualPaneProps) {
  const pane = useBilingualPane({ docId, direction, pdfScrollRef, pageNodes, zoom });
  const { current, revealBlock, onPaneScroll } = pane.linked;

  return (
    <aside
      data-testid="bilingual-pane"
      data-direction={direction}
      data-current-block={current ?? undefined}
      data-scale={scaleFor(zoom)}
      aria-label="中英对照"
      className="flex w-[42%] max-w-[560px] min-w-[300px] shrink-0 flex-col border-l border-border bg-surface"
    >
      <BilingualHeader
        direction={direction}
        onDirection={onDirection}
        fontSize={pane.fontSize}
        onFontSize={pane.setFontSize}
        onClose={onClose}
      />
      <div
        ref={pane.paneRef}
        data-bilingual-scroll
        onScroll={onPaneScroll}
        className="app-scroll min-h-0 flex-1 px-3 py-2"
      >
        <PaneBody
          pending={pane.query.isPending}
          error={pane.query.isError ? pane.query.error.message : null}
          onRetry={() => {
            void pane.query.refetch();
          }}
          blocks={pane.blocks}
          current={current}
          fontSize={pane.fontSize}
          direction={direction}
          onReveal={revealBlock}
          rowRef={pane.setRow}
          onOpenTranslateTab={onOpenTranslateTab}
        />
      </div>
    </aside>
  );
}

function useBilingualPane({
  docId,
  direction,
  pdfScrollRef,
  pageNodes,
  zoom,
}: Pick<BilingualPaneProps, "docId" | "direction" | "pdfScrollRef" | "pageNodes" | "zoom">) {
  const [fontSize, setFontSize] = useState(DEFAULT_FONT);
  const paneRef = useRef<HTMLDivElement | null>(null);
  const rows = useRef(new Map<string, HTMLDivElement>());

  const query = useQuery({
    queryKey: ["translation", docId, direction],
    queryFn: () => fetchTranslation(docId, direction),
    enabled: Boolean(docId),
  });
  const blocks = useMemo(() => query.data?.blocks ?? [], [query.data]);
  const linked = useLinkedScroll({ pdfScrollRef, pageNodes, paneRef, rows, blocks, zoom });
  const setRow = useCallback((id: string, node: HTMLDivElement | null) => {
    if (node) rows.current.set(id, node);
    else rows.current.delete(id);
  }, []);

  return { fontSize, setFontSize, paneRef, query, blocks, linked, setRow };
}

function BilingualHeader({
  direction,
  onDirection,
  fontSize,
  onFontSize,
  onClose,
}: {
  direction: Direction;
  onDirection: (direction: Direction) => void;
  fontSize: number;
  onFontSize: (size: number) => void;
  onClose: () => void;
}) {
  return (
    <div className="shrink-0 border-b border-border px-2.5 py-1.5">
      <div className="flex min-h-6 items-center gap-1.5">
        <Languages className="size-4 shrink-0 text-ink-2" aria-hidden />
        <span className="text-[var(--text-sm)] font-medium text-ink">中英对照</span>
        <button
          type="button"
          aria-label="退出对照模式"
          onClick={onClose}
          className="ml-auto rounded p-1 text-ink-2 hover:bg-surface-2 hover:text-ink"
        >
          <X className="size-4" aria-hidden />
        </button>
      </div>
      <div className="mt-1 flex items-center justify-between gap-2">
        <DirectionSwitch direction={direction} onDirection={onDirection} />
        <div className="flex items-center gap-0.5">
          <FontSizeControls fontSize={fontSize} onFontSize={onFontSize} />
        </div>
      </div>
    </div>
  );
}

function DirectionSwitch({
  direction,
  onDirection,
}: {
  direction: Direction;
  onDirection: (direction: Direction) => void;
}) {
  return (
    <div className="flex rounded-control border border-border p-0.5" role="group" aria-label="对照翻译方向">
      {(Object.keys(LABEL) as Direction[]).map((key) => (
        <button
          key={key}
          type="button"
          aria-pressed={direction === key}
          onClick={() => {
            onDirection(key);
          }}
          className={cn(
            "rounded-[6px] px-1.5 py-0.5 text-[var(--text-xs)] transition-colors duration-[--dur-fast]",
            direction === key ? "bg-primary text-white" : "text-ink-2 hover:text-ink",
          )}
        >
          {LABEL[key]}
        </button>
      ))}
    </div>
  );
}

function FontSizeControls({
  fontSize,
  onFontSize,
}: {
  fontSize: number;
  onFontSize: (size: number) => void;
}) {
  return (
    <>
      <button
        type="button"
        aria-label="减小译文字号"
        disabled={fontSize <= MIN_FONT}
        onClick={() => {
          onFontSize(Math.max(MIN_FONT, fontSize - 1));
        }}
        className="rounded p-1 text-ink-2 hover:bg-surface-2 hover:text-ink disabled:opacity-40"
      >
        <Minus className="size-3.5" aria-hidden />
      </button>
      <span className="w-6 text-center text-[var(--text-2xs)] tabular-nums text-ink-2" data-testid="bilingual-font-size">
        {fontSize}
      </span>
      <button
        type="button"
        aria-label="增大译文字号"
        disabled={fontSize >= MAX_FONT}
        onClick={() => {
          onFontSize(Math.min(MAX_FONT, fontSize + 1));
        }}
        className="rounded p-1 text-ink-2 hover:bg-surface-2 hover:text-ink disabled:opacity-40"
      >
        <Plus className="size-3.5" aria-hidden />
      </button>
    </>
  );
}

interface PaneBodyProps {
  pending: boolean;
  error: string | null;
  onRetry: () => void;
  blocks: readonly TranslationBlock[];
  current: string | null;
  fontSize: number;
  direction: Direction;
  onReveal: (id: string) => void;
  rowRef: (id: string, node: HTMLDivElement | null) => void;
  onOpenTranslateTab: () => void;
}

function PaneBody({
  pending,
  error,
  onRetry,
  blocks,
  current,
  fontSize,
  direction,
  onReveal,
  rowRef,
  onOpenTranslateTab,
}: PaneBodyProps) {
  if (pending) return <PaneSkeleton />;
  if (error) return <ErrorState message="无法读取译文" detail={error} onRetry={onRetry} />;
  if (blocks.length === 0) return <EmptyTranslation onOpenTranslateTab={onOpenTranslateTab} />;
  return (
    <>
      <p className="mb-2 border-b border-border pb-1.5 text-[var(--text-2xs)] text-ink-2">
        按段落对齐 · 拖动任一栏，另一栏跟随
      </p>
      {blocks.map((block) => (
        <BilingualRow
          key={block.block_id}
          block={block}
          current={current === block.block_id}
          fontSize={fontSize}
          direction={direction}
          onReveal={onReveal}
          rowRef={rowRef}
        />
      ))}
    </>
  );
}

function EmptyTranslation({ onOpenTranslateTab }: { onOpenTranslateTab: () => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center px-6 text-center" data-testid="bilingual-empty">
      <Languages className="size-7 text-ink-2" aria-hidden />
      <p className="mt-2 text-[var(--text-sm)] font-medium text-ink">尚无译文</p>
      <p className="mt-1 text-[var(--text-xs)] leading-relaxed text-ink-2">
        整篇翻译完成后，这里会按段落对齐原文，拖动任一侧即可联动阅读。
      </p>
      <button
        type="button"
        onClick={onOpenTranslateTab}
        className="mt-3 rounded-control bg-primary px-3 py-1.5 text-[var(--text-sm)] font-medium text-white"
      >
        前往翻译
      </button>
    </div>
  );
}

function BilingualRow({
  block,
  current,
  fontSize,
  direction,
  onReveal,
  rowRef,
}: {
  block: TranslationBlock;
  current: boolean;
  fontSize: number;
  direction: Direction;
  onReveal: (id: string) => void;
  rowRef: (id: string, node: HTMLDivElement | null) => void;
}) {
  return (
    <div
      ref={(node) => {
        rowRef(block.block_id, node);
      }}
      data-bilingual-row={block.block_id}
      data-page={block.page}
      data-bbox={block.bbox.join(",")}
      role="button"
      tabIndex={0}
      aria-current={current ? "true" : undefined}
      onClick={() => {
        onReveal(block.block_id);
      }}
      onKeyDown={(event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        onReveal(block.block_id);
      }}
      className={cn(
        "mb-1 cursor-pointer rounded-control border-l-2 px-2 py-1.5 transition-colors duration-[--dur-fast]",
        current ? "border-primary bg-primary/5" : "border-transparent hover:bg-surface-2",
      )}
    >
      <div className="mb-0.5 flex items-center gap-2 text-[var(--text-2xs)] text-ink-2">
        <span className="tabular-nums">第 {block.page} 页</span>
        {block.type === "heading" && <span className="rounded bg-surface-2 px-1">标题</span>}
        {block.type === "caption" && <span className="rounded bg-surface-2 px-1">图表注</span>}
      </div>
      <p
        lang={direction === "en2zh" ? "zh-CN" : "en"}
        className={cn("whitespace-pre-wrap leading-relaxed text-ink", block.type === "heading" && "font-semibold")}
        style={{ fontSize }}
      >
        {block.translation}
      </p>
    </div>
  );
}

function PaneSkeleton() {
  return (
    <div className="space-y-3 py-2" data-testid="bilingual-loading">
      {Array.from({ length: 8 }, (_, index) => (
        <div key={index}>
          <Skeleton className="h-2.5 w-14" />
          <Skeleton className="mt-1.5 h-4 w-full" />
          <Skeleton className="mt-1 h-4 w-4/5" />
        </div>
      ))}
    </div>
  );
}
