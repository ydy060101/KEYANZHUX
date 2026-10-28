import { AlertTriangle, Download } from "lucide-react";

import { Button } from "@/design/Button";
import { cn } from "@/lib/cn";
import { AnchorChip } from "./AnchorChip";
import { NOT_FOUND, type CompareTable as Table, type QaAnchor } from "./api";
import { compareToMarkdown, downloadMarkdown } from "./markdown";

export interface CompareTableProps {
  table: Table;
  documents: Record<string, string>;
  onOpenAnchor: (anchor: QaAnchor) => void;
}

/**
 * The compare-mode answer (02 §4.3): rows are dimensions, columns are papers,
 * every grounded cell carries the anchor that proves it, and an empty cell
 * says so instead of guessing (H02).
 */
export function CompareAnswer({ table, documents, onOpenAnchor }: CompareTableProps) {
  const first = table.table[0];
  const ids = first ? Object.keys(first.cells) : [];
  const exportTable = () => {
    downloadMarkdown(
      `多文对比-${new Date().toISOString().slice(0, 10)}.md`,
      compareToMarkdown(table, documents),
    );
  };

  return (
    <div className="space-y-3" data-testid="compare-table">
      <div className="flex flex-wrap items-start gap-2">
        <p className="min-w-0 flex-1 text-[var(--text-base)] leading-relaxed text-ink">{table.summary}</p>
        <Button variant="secondary" size="sm" onClick={exportTable} aria-label="导出 Markdown">
          <Download className="size-3.5" aria-hidden />
          导出 Markdown
        </Button>
      </div>

      <div className="overflow-x-auto rounded-card border border-border">
        <table className="w-full min-w-[560px] border-collapse text-left text-[var(--text-sm)]">
          <thead className="bg-surface-2">
            <tr>
              <th scope="col" className="w-[150px] px-3 py-2 font-medium text-ink-2">
                维度
              </th>
              {ids.map((id) => (
                <th key={id} scope="col" className="px-3 py-2 font-medium text-ink">
                  <span className="line-clamp-2" title={documents[id] ?? id}>
                    {documents[id] ?? id}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.table.map((row) => (
              <tr key={row.dimension} className="border-t border-border align-top">
                <th scope="row" className="px-3 py-2.5 font-medium text-ink">
                  {row.dimension}
                </th>
                {ids.map((id) => {
                  const value = row.cells[id];
                  if (!value) {
                    return (
                      <td key={id} className="px-3 py-2.5 text-ink-2">
                        —
                      </td>
                    );
                  }
                  const missing = value.text === NOT_FOUND;
                  return (
                    <td key={id} className="px-3 py-2.5">
                      <p className={cn("leading-relaxed", missing ? "text-ink-2" : "text-ink")}>
                        {value.text}
                      </p>
                      {value.citations.length > 0 && (
                        <div className="mt-1.5 flex flex-wrap gap-1">
                          {value.citations.map((anchor) => (
                            <AnchorChip
                              key={`${anchor.doc_id}:${anchor.block_id}`}
                              anchor={anchor}
                              docTitle={documents[anchor.doc_id] ?? anchor.doc_id}
                              onOpen={onOpenAnchor}
                            />
                          ))}
                        </div>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {table.flags.length > 0 && (
        <details className="rounded-control border border-border bg-surface-2 px-3 py-2">
          <summary className="flex cursor-pointer items-center gap-1.5 text-[var(--text-xs)] text-ink-2">
            <AlertTriangle className="size-3.5 text-warn-text" aria-hidden />
            校验提示（{table.flags.length}）
          </summary>
          <ul className="mt-2 space-y-1 text-[var(--text-xs)] text-ink-2">
            {table.flags.map((flag, index) => (
              <li key={`${flag.kind}-${index}`}>{flag.text}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
