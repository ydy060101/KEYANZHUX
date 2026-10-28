import { NOT_FOUND, type CompareTable } from "./api";

/** Escape the cell text so a pipe inside a value cannot break the table. */
function cell(value: string): string {
  return value.replace(/\|/g, "\\|").replace(/\s+/g, " ").trim();
}

/**
 * Export a compare table as Markdown (02 §4.3).
 *
 * The table is the answer, so the export carries the same cells, their pages
 * and the counted summary; no prose is added that the table does not support.
 */
export function compareToMarkdown(table: CompareTable, documents: Record<string, string>): string {
  const first = table.table[0];
  const ids = first ? Object.keys(first.cells) : [];
  const headers = ids.map((id) => cell(documents[id] ?? id));
  const lines: string[] = ["# 多文对比", "", table.summary, ""];

  if (ids.length > 0) {
    lines.push(`| 维度 | ${headers.join(" | ")} |`);
    lines.push(`| --- | ${ids.map(() => "---").join(" | ")} |`);
    for (const row of table.table) {
      const cells = ids.map((id) => {
        const value = row.cells[id];
        if (!value) return "—";
        if (value.text === NOT_FOUND) return NOT_FOUND;
        const pages = [...new Set(value.citations.map((anchor) => `p.${anchor.page}`))];
        return `${cell(value.text)}${pages.length > 0 ? `（${pages.join(", ")}）` : ""}`;
      });
      lines.push(`| ${cell(row.dimension)} | ${cells.join(" | ")} |`);
    }
  }

  const sources = new Map<string, Set<number>>();
  for (const row of table.table) {
    for (const id of ids) {
      for (const anchor of row.cells[id]?.citations ?? []) {
        const pages = sources.get(anchor.doc_id) ?? new Set<number>();
        pages.add(anchor.page);
        sources.set(anchor.doc_id, pages);
      }
    }
  }
  if (sources.size > 0) {
    lines.push("", "## 出处");
    for (const [docId, pages] of sources) {
      const title = documents[docId] ?? docId;
      lines.push(`- ${title}：第 ${[...pages].sort((a, b) => a - b).join("、")} 页`);
    }
  }
  if (table.flags.length > 0) {
    lines.push("", "## 校验提示");
    for (const flag of table.flags) lines.push(`- ${flag.text}`);
  }
  return `${lines.join("\n")}\n`;
}

/** Save a Markdown string through a temporary object URL. */
export function downloadMarkdown(filename: string, body: string): void {
  const blob = new Blob([body], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
