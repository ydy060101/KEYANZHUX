import * as Tooltip from "@radix-ui/react-tooltip";
import { Quote } from "lucide-react";

import { cn } from "@/lib/cn";
import type { QaAnchor } from "./api";

export interface AnchorChipProps {
  anchor: QaAnchor;
  marker?: string;
  quote?: string;
  docTitle: string;
  onOpen: (anchor: QaAnchor) => void;
  className?: string;
}

/**
 * One source chip (02 §4.3): `[1]` inline after a claim, `p.8` in a compare
 * cell. Hovering shows the paper, page and the quote H04 verified; clicking
 * opens the anchor in the split reader. The tooltip is portalled so a long
 * chat scroll container cannot clip it.
 */
export function AnchorChip({ anchor, marker, quote, docTitle, onOpen, className }: AnchorChipProps) {
  const label = marker ?? `p.${anchor.page}`;
  return (
    // Self-contained provider: the chip renders from the QA page, the reader
    // rail and the compare table, none of which owns a shared provider.
    <Tooltip.Provider delayDuration={120}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>
          <button
            type="button"
            data-anchor-chip
            data-marker={marker}
            aria-label={marker ? `引用 ${marker}，第 ${anchor.page} 页` : `查看第 ${anchor.page} 页原文`}
            onClick={() => {
              onOpen(anchor);
            }}
            className={cn(
              "inline-flex items-center gap-1 rounded-full border border-border bg-surface-2 px-2 py-0.5",
              "align-middle text-[var(--text-xs)] font-medium text-primary transition-colors duration-[--dur-fast]",
              "hover:border-primary hover:bg-surface",
              className,
            )}
          >
            <Quote className="size-3" strokeWidth={2} aria-hidden />
            {label}
          </button>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content
            side="top"
            align="center"
            sideOffset={6}
            collisionPadding={12}
            className="z-50 w-[300px] rounded-card border border-border bg-surface p-3 text-left shadow-lg"
          >
            <p className="truncate text-[var(--text-sm)] font-medium text-ink" title={docTitle}>
              {docTitle}
            </p>
            <p className="mt-0.5 text-[var(--text-xs)] text-ink-2">第 {anchor.page} 页</p>
            {quote && (
              <p className="mt-2 line-clamp-3 text-[var(--text-xs)] leading-relaxed text-ink-2">
                “{quote}”
              </p>
            )}
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
}
