import { ExternalLink } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { cn } from "@/lib/cn";
import type { Asset, DocMeta, Ref } from "./api";
import { ReferenceList, type CitationTarget } from "./CitationCard";

/**
 * The right rail's `结构` tab (02 §4.2): metadata, tables, figures, formulas,
 * references and the appendix, each row able to jump to where it came from.
 *
 * The lists come from `/structure` (assets + outline + references), not from
 * block text, so opening the panel on a 541-page book costs one small
 * request. Table HTML is rendered when the parse extracted it, with the page
 * crop as the fallback the card requires.
 */

type Tab = "meta" | "figures" | "tables" | "formulas" | "references";

const TABS: { key: Tab; label: string }[] = [
  { key: "meta", label: "概览" },
  { key: "figures", label: "图表" },
  { key: "tables", label: "表格" },
  { key: "formulas", label: "公式" },
  { key: "references", label: "参考文献" },
];

/**
 * Which asset kind each tab counts. The keys differ — the tab is `figures`,
 * the asset kind is `figure` — and indexing `counts` by the tab key printed
 * "图表 undefined" for the three asset tabs.
 */
const KIND: Partial<Record<Tab, "figure" | "table" | "formula">> = {
  figures: "figure",
  tables: "table",
  formulas: "formula",
};

export interface StructurePanelProps {
  meta: DocMeta | undefined;
  assets: Asset[];
  references: Ref[];
  flashRefId: string | null;
  lastCitation: CitationTarget | null;
  onJumpPage: (page: number, blockId?: string) => void;
  onJumpReference: (reference: Ref) => void;
  onBackToCitation: (reference: Ref) => void;
}

export function StructurePanel(props: StructurePanelProps) {
  const [tab, setTab] = useState<Tab>("meta");
  const counts = useMemo(() => countKinds(props.assets), [props.assets]);

  // Jumping to a bibliography entry from a citation marker must land the
  // reader on that entry: the panel keeps its own tab, so following a marker
  // would otherwise highlight a row the reader cannot see. `flashRefId` is set
  // by the jump itself, which is exactly when the entry is the thing to show.
  const { flashRefId } = props;
  useEffect(() => {
    if (flashRefId) setTab("references");
  }, [flashRefId]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 gap-0.5 overflow-x-auto border-b border-border px-1.5 py-1" role="tablist" aria-label="结构分类">
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            onClick={() => {
              setTab(key);
            }}
            className={cn(
              "shrink-0 rounded-control px-2 py-1 text-[var(--text-xs)] transition-colors duration-[--dur-fast]",
              tab === key ? "bg-surface-2 font-medium text-primary" : "text-ink-2 hover:text-ink",
            )}
          >
            {label}
            {KIND[key] !== undefined ? ` ${String(counts[KIND[key]])}` : ""}
          </button>
        ))}
      </div>
      <div className="app-scroll min-h-0 flex-1 p-3">
        {tab === "meta" && <MetaCard meta={props.meta} onJumpPage={props.onJumpPage} />}
        {tab === "figures" && (
          <AssetGrid kind="figure" assets={props.assets} onJumpPage={props.onJumpPage} />
        )}
        {tab === "tables" && (
          <AssetGrid kind="table" assets={props.assets} onJumpPage={props.onJumpPage} />
        )}
        {tab === "formulas" && (
          <AssetGrid kind="formula" assets={props.assets} onJumpPage={props.onJumpPage} />
        )}
        {tab === "references" && (
          <ReferenceList
            references={props.references}
            flashId={props.flashRefId}
            lastCitation={props.lastCitation}
            onJump={props.onJumpReference}
            onBackTo={props.onBackToCitation}
          />
        )}
      </div>
    </div>
  );
}

function countKinds(assets: Asset[]): Record<"figure" | "table" | "formula", number> {
  const counts = { figure: 0, table: 0, formula: 0 };
  for (const asset of assets) counts[asset.kind] += 1;
  return counts;
}

function MetaCard({ meta, onJumpPage }: { meta: DocMeta | undefined; onJumpPage: (page: number) => void }) {
  if (!meta) {
    return <p className="py-4 text-[var(--text-sm)] text-ink-2">没有可用的元信息。</p>;
  }
  const abstract = meta.abstract;
  const authors = meta.authors ?? [];
  return (
    <div className="space-y-3">
      <section>
        <h3 className="mb-1 text-[var(--text-xs)] font-medium uppercase tracking-wide text-ink-2">标题</h3>
        <p className="text-[var(--text-md)] font-medium leading-snug text-ink">{meta.title || "—"}</p>
      </section>
      <section>
        <h3 className="mb-1 text-[var(--text-xs)] font-medium uppercase tracking-wide text-ink-2">作者</h3>
        {authors.length === 0 ? (
          <p className="text-[var(--text-sm)] text-ink-2">原文未找到作者信息。</p>
        ) : (
          <ul className="space-y-1">
            {authors.map((author, index) => (
              <li key={`${author.name}-${String(index)}`} className="text-[var(--text-sm)] text-ink">
                {author.name}
                {author.affiliation && (
                  <span className="ml-1.5 text-[var(--text-xs)] text-ink-2">{author.affiliation}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
      <section>
        <h3 className="mb-1 flex items-center gap-1 text-[var(--text-xs)] font-medium uppercase tracking-wide text-ink-2">
          摘要
          {abstract?.anchor && (
            <button
              type="button"
              onClick={() => {
                onJumpPage(abstract.anchor?.page ?? 1);
              }}
              className="text-primary hover:underline"
              aria-label="跳到摘要原文"
            >
              <ExternalLink className="size-3" aria-hidden />
            </button>
          )}
        </h3>
        <p className="text-[var(--text-sm)] leading-relaxed text-ink">
          {abstract?.text ?? "原文未找到摘要。"}
        </p>
      </section>
    </div>
  );
}

function AssetGrid({
  kind,
  assets,
  onJumpPage,
}: {
  kind: Asset["kind"];
  assets: Asset[];
  onJumpPage: (page: number) => void;
}) {
  const items = assets.filter((asset) => asset.kind === kind);
  if (items.length === 0) {
    return <p className="py-4 text-[var(--text-sm)] text-ink-2">没有解析出{LABEL[kind]}。</p>;
  }
  return (
    <ul className="space-y-2">
      {items.map((asset) => (
        <li key={asset.id}>
          <AssetItem asset={asset} onJumpPage={onJumpPage} />
        </li>
      ))}
    </ul>
  );
}

/**
 * One asset: a table shows its extracted HTML with the crop one click away
 * (02 §4.2), a figure or formula shows the crop itself.
 */
function AssetItem({ asset, onJumpPage }: { asset: Asset; onJumpPage: (page: number) => void }) {
  const [showCrop, setShowCrop] = useState(false);
  const html = asset.html ?? null;
  return (
    <div className="overflow-hidden rounded-control border border-border">
      <button
        type="button"
        onClick={() => {
          onJumpPage(asset.page);
        }}
        className="block w-full text-left"
      >
        {html && !showCrop ? (
          <div
            className="max-h-64 overflow-auto bg-surface p-2 text-[var(--text-xs)] [&_td]:border [&_td]:border-border [&_td]:px-1 [&_td]:py-0.5 [&_th]:border [&_th]:border-border [&_th]:px-1 [&_th]:py-0.5 [&_table]:w-full"
            // The HTML was produced by parsing this document, not entered by a user.
            dangerouslySetInnerHTML={{ __html: html }}
          />
        ) : (
          <img
            src={asset.path}
            alt={`${LABEL[asset.kind]} 第 ${String(asset.page)} 页`}
            loading="lazy"
            className="max-h-64 w-full bg-surface-2 object-contain"
          />
        )}
      </button>
      <div className="flex items-center gap-2 border-t border-border px-1.5 py-1">
        <span className="text-[var(--text-xs)] text-ink-2">
          {LABEL[asset.kind]} · 第 {asset.page} 页
        </span>
        {html && (
          <button
            type="button"
            className="ml-auto text-[var(--text-xs)] text-primary hover:underline"
            onClick={() => {
              setShowCrop((prev) => !prev);
            }}
          >
            {showCrop ? "查看 HTML" : "查看原图"}
          </button>
        )}
      </div>
    </div>
  );
}

const LABEL: Record<Asset["kind"], string> = { figure: "图", table: "表", formula: "公式" };
