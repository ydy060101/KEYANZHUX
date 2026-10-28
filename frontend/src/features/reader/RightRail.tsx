import type { QaAnchor } from "@/features/qa/api";
import { ReaderQaPanel } from "@/features/qa/ReaderQaPanel";
import { cn } from "@/lib/cn";
import type { Asset, DocMeta, Ref } from "./api";
import type { CitationTarget } from "./CitationCard";
import { StructurePanel } from "./StructurePanel";
import { TranslatePanel, type TranslateRequest } from "./TranslatePanel";

export type RightTab = "structure" | "qa" | "translate";

const TABS: { key: RightTab; label: string }[] = [
  { key: "structure", label: "结构" },
  { key: "qa", label: "问答" },
  { key: "translate", label: "翻译" },
];

export interface RightRailProps {
  tab: RightTab;
  onTab: (tab: RightTab) => void;
  meta: DocMeta | undefined;
  assets: Asset[];
  references: Ref[];
  flashRefId: string | null;
  lastCitation: CitationTarget | null;
  onJumpPage: (page: number) => void;
  onJumpReference: (reference: Ref) => void;
  onBackToCitation: (reference: Ref) => void;
  docId: string;
  docTitle: string;
  onOpenAnchor: (anchor: QaAnchor) => void;
  translateRequest: TranslateRequest | null;
}

/** The reader's right rail (02 §4.2): structure, QA and translation tabs. */
export function RightRail({
  tab,
  onTab,
  meta,
  assets,
  references,
  flashRefId,
  lastCitation,
  onJumpPage,
  onJumpReference,
  onBackToCitation,
  docId,
  docTitle,
  onOpenAnchor,
  translateRequest,
}: RightRailProps) {
  return (
    <aside className="flex w-[340px] shrink-0 flex-col border-l border-border bg-surface">
      <div className="flex border-b border-border" role="tablist" aria-label="右栏">
        {TABS.map((item) => (
          <button
            key={item.key}
            role="tab"
            aria-selected={tab === item.key}
            onClick={() => {
              onTab(item.key);
            }}
            className={cn(
              "flex-1 py-2 text-[var(--text-sm)]",
              tab === item.key ? "border-b-2 border-primary font-medium text-primary" : "text-ink-2",
            )}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div className="flex min-h-0 flex-1 flex-col">
        {tab === "structure" && (
          <StructurePanel
            meta={meta}
            assets={assets}
            references={references}
            flashRefId={flashRefId}
            lastCitation={lastCitation}
            onJumpPage={onJumpPage}
            onJumpReference={onJumpReference}
            onBackToCitation={onBackToCitation}
          />
        )}
        {tab === "qa" && (
          <ReaderQaPanel docId={docId} docTitle={docTitle} onOpenAnchor={onOpenAnchor} />
        )}
        {tab === "translate" && (
          <TranslatePanel docId={docId} request={translateRequest} />
        )}
      </div>
    </aside>
  );
}
