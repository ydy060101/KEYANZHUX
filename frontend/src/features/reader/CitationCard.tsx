import { ArrowLeftRight, Library } from "lucide-react";
import { useState } from "react";

import { Button } from "@/design/Button";
import { cn } from "@/lib/cn";
import type { Ref } from "./api";

/**
 * Citation markers and their hover cards (02 §4.2).
 *
 * A marker such as `[11]` is a box the reader draws over the page from the
 * bbox the parser recorded; hovering it shows the reference it points at, and
 * clicking scrolls to the bibliography entry. The bibliography entry then
 * offers "返回引用处", which is the other half of the bidirectional jump.
 */

export interface CitationTarget {
  /** Where the marker sits, so "返回引用处" can come back to it. */
  page: number;
  blockId: string;
}

/** The card shown when a marker is hovered or focused. */

/** The card shown when a marker is hovered or focused. */export function CitationCard({
  marker,
  references,
  onOpen,
  onJump,
}: {
  marker: string;
  references: Ref[];
  onOpen: (ref: Ref) => void;
  onJump: (ref: Ref) => void;
}) {
  if (references.length === 0) {
    return (
      <div
        className="w-64 rounded-card border border-border bg-surface p-3 shadow-md"
        role="dialog"
        aria-label={`引用 ${marker}`}
      >
        <p className="text-[var(--text-sm)] text-ink-2">{marker} 没有对应的参考文献条目。</p>
      </div>
    );
  }
  return (
    <div className="w-80 rounded-card border border-border bg-surface p-3 shadow-md" role="dialog" aria-label={`引用 ${marker}`}>
      {references.map((reference) => (
        <div key={reference.id} className="space-y-1.5 border-b border-border py-2 first:pt-0 last:border-b-0 last:pb-0">
          <p className="text-[var(--text-sm)] font-medium leading-snug text-ink">
            {reference.title ?? reference.raw}
          </p>
          <p className="text-[var(--text-xs)] text-ink-2">
            {reference.authors.slice(0, 3).join(", ")}
            {reference.authors.length > 3 ? " 等" : ""}
            {reference.year ? ` · ${String(reference.year)}` : ""}
          </p>
          <div className="flex items-center gap-2">
            <WorthMeter score={reference.worth_score} />
            <div className="ml-auto flex gap-1">
              <Button size="sm" variant="ghost" onClick={() => { onJump(reference); }}>
                跳转
              </Button>
              <Button size="sm" variant="secondary" onClick={() => { onOpen(reference); }}>
                <Library className="size-3.5" aria-hidden />
                入库
              </Button>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

/** 含金量 (02 §4.2): a 0–100 score, or an honest "未评分". */
export function WorthMeter({ score }: { score: number | undefined }) {
  if (score === undefined) {
    return <span className="text-[var(--text-xs)] text-ink-2">含金量未评分</span>;
  }
  return (
    <span className="flex items-center gap-1.5" title={`含金量 ${String(score)}/100`}>
      <span className="h-1 w-14 overflow-hidden rounded-full bg-surface-2">
        <span className="block h-full rounded-full bg-accent" style={{ width: `${String(score)}%` }} />
      </span>
      <span className="text-[var(--text-xs)] text-ink-2">{Math.round(score)}</span>
    </span>
  );
}

/** The bibliography list in the structure panel. */
export function ReferenceList({
  references,
  flashId,
  onJump,
  onBackTo,
  lastCitation,
}: {
  references: Ref[];
  flashId: string | null;
  onJump: (reference: Ref) => void;
  onBackTo: (reference: Ref) => void;
  lastCitation: CitationTarget | null;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  if (references.length === 0) {
    return <p className="px-1 py-4 text-[var(--text-sm)] text-ink-2">没有解析出参考文献。</p>;
  }
  return (
    <ul className="space-y-1.5">
      {references.map((reference) => {
        const open = expanded.has(reference.id);
        return (
          <li
            key={reference.id}
            data-ref-id={reference.id}
            className={cn(
              "rounded-control border p-2 transition-colors duration-[--dur-slow]",
              flashId === reference.id ? "border-primary bg-[var(--hl)]" : "border-border",
            )}
          >
            <button
              type="button"
              onClick={() => {
                onJump(reference);
              }}
              className="block w-full text-left"
            >
              <p className="text-[var(--text-xs)] text-ink-2">[{reference.index}]</p>
              <p className={cn("text-[var(--text-sm)] text-ink", !open && "line-clamp-2")}>
                {reference.title ?? reference.raw}
              </p>
            </button>
            <div className="mt-1 flex items-center gap-2">
              <WorthMeter score={reference.worth_score} />
              <div className="ml-auto flex gap-1">
                {lastCitation && (
                  <Button size="sm" variant="ghost" onClick={() => { onBackTo(reference); }}>
                    <ArrowLeftRight className="size-3.5" aria-hidden />
                    返回引用处
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setExpanded((prev) => {
                      const next = new Set(prev);
                      if (next.has(reference.id)) next.delete(reference.id);
                      else next.add(reference.id);
                      return next;
                    });
                  }}
                >
                  {open ? "收起" : "展开"}
                </Button>
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
