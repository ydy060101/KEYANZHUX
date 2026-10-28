import { FileText, Image } from "lucide-react";

import { cn } from "@/lib/cn";
import type { OutlineItem } from "./api";
import { OutlinePanel } from "./OutlinePanel";
import { Thumbnails } from "./ReaderToolbar";

export type LeftTab = "toc" | "thumbs";

export interface LeftRailProps {
  tab: LeftTab;
  onTab: (tab: LeftTab) => void;
  outline: OutlineItem[];
  activeId: string | null;
  onPick: (item: OutlineItem) => void;
  total: number;
  page: number;
  onPickPage: (page: number) => void;
}

/** The reader's left rail (02 §4.2): outline and thumbnails. */
export function LeftRail({
  tab,
  onTab,
  outline,
  activeId,
  onPick,
  total,
  page,
  onPickPage,
}: LeftRailProps) {
  return (
    <aside className="flex w-[248px] shrink-0 flex-col border-r border-border bg-surface">
      <div className="flex border-b border-border" role="tablist" aria-label="左栏">
        {(["toc", "thumbs"] as const).map((key) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            onClick={() => {
              onTab(key);
            }}
            className={cn(
              "flex flex-1 items-center justify-center gap-1.5 py-2 text-[var(--text-sm)]",
              tab === key
                ? "border-b-2 border-primary font-medium text-primary"
                : "text-ink-2",
            )}
          >
            {key === "toc" ? (
              <FileText className="size-3.5" aria-hidden />
            ) : (
              <Image className="size-3.5" aria-hidden />
            )}
            {key === "toc" ? "目录" : "缩略图"}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1">
        {tab === "toc" ? (
          <OutlinePanel items={outline} activeId={activeId} onPick={onPick} />
        ) : (
          <Thumbnails total={total} current={page} onPick={onPickPage} />
        )}
      </div>
    </aside>
  );
}
