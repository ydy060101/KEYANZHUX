import { FileText, MoreHorizontal, Search, Upload } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/design/Button";
import { EmptyState } from "@/design/States";
import { cn } from "@/lib/cn";
import { mockDocuments, type Document } from "@/mocks/data";

const STATUS_LABEL: Record<Document["status"], string> = {
  uploading: "上传中",
  parsing: "解析中",
  ready: "已就绪",
  partial: "部分可用",
  failed: "失败",
};

const STATUS_STYLE: Record<Document["status"], string> = {
  uploading: "text-ink-2",
  parsing: "text-warn-text",
  ready: "text-success-text",
  partial: "text-warn-text",
  failed: "text-danger-text",
};

type SourceKind = NonNullable<Document["source_kind"]>;
const SOURCE_LABEL: Record<SourceKind, string> = {
  vector: "矢量",
  scanned: "扫描",
  mixed: "混合",
};

export function LibraryPage() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [view, setView] = useState<"card" | "table">("card");
  const [dragging, setDragging] = useState(false);

  const documents = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return mockDocuments;
    return mockDocuments.filter(
      (doc) => doc.title.toLowerCase().includes(q) || (doc.arxiv_id ?? "").includes(q),
    );
  }, [query]);

  return (
    <div
      className="flex h-full flex-col"
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => {
        setDragging(false);
      }}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
      }}
    >
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border px-6 py-3">
        <div className="flex h-9 min-w-[220px] flex-1 items-center gap-2 rounded-control border border-border bg-surface px-3">
          <Search className="size-4 text-ink-2" strokeWidth={1.75} aria-hidden />
          <input
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
            }}
            placeholder="按标题或 arXiv ID 搜索"
            aria-label="搜索文献"
            className="w-full bg-transparent text-[var(--text-base)] text-ink outline-none placeholder:text-ink-2"
          />
        </div>
        <div className="flex rounded-control border border-border p-0.5" role="group" aria-label="视图切换">
          {(["card", "table"] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              aria-pressed={view === mode}
              onClick={() => {
                setView(mode);
              }}
              className={cn(
                "rounded-[6px] px-3 py-1 text-[var(--text-sm)]",
                view === mode ? "bg-surface-2 font-medium text-ink" : "text-ink-2 hover:text-ink",
              )}
            >
              {mode === "card" ? "卡片" : "表格"}
            </button>
          ))}
        </div>
        <Button variant="primary">
          <Upload className="size-4" aria-hidden />
          上传 PDF
        </Button>
      </div>

      <div className="app-scroll flex-1 px-6 py-5">
        {documents.length === 0 ? (
          <EmptyState
            title="没有匹配的文献"
            description="换一个关键词，或把 PDF 拖到此处开始解析。"
            icon={<FileText className="size-6" aria-hidden />}
          />
        ) : view === "card" ? (
          <ul className="grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-4">
            {documents.map((doc) => (
              <li key={doc.id}>
                <article
                  className={cn(
                    "group flex h-full flex-col gap-2 rounded-card border border-border bg-surface p-4 transition-shadow duration-[--dur-fast] hover:shadow-md",
                  )}
                >
                  <div className="flex items-start gap-2">
                    <h3 className="min-w-0 flex-1 text-[var(--text-base)] font-medium leading-snug text-ink">
                      {doc.title}
                    </h3>
                    {doc.version && (
                      <span className="shrink-0 rounded-full bg-surface-2 px-2 py-0.5 text-[var(--text-xs)] text-ink-2">
                        {doc.version}
                      </span>
                    )}
                  </div>
                  <p className="text-[var(--text-sm)] text-ink-2">
                    {doc.arxiv_id ? `arXiv:${doc.arxiv_id}` : "本地文件"} · {doc.page_count} 页 ·{" "}
                    {SOURCE_LABEL[doc.source_kind ?? "vector"]}
                  </p>
                  <p className={cn("text-[var(--text-sm)]", STATUS_STYLE[doc.status])}>
                    {STATUS_LABEL[doc.status]}
                  </p>
                  <div className="mt-auto flex items-center gap-2 pt-2">
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => {
                        navigate(`/reader/${doc.id}`);
                      }}
                    >
                      打开
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        navigate("/qa");
                      }}
                    >
                      问答
                    </Button>
                    <button
                      type="button"
                      aria-label={`更多操作：${doc.title}`}
                      className="ml-auto rounded p-1 text-ink-2 opacity-0 transition-opacity group-hover:opacity-100 hover:text-ink focus-visible:opacity-100"
                    >
                      <MoreHorizontal className="size-4" aria-hidden />
                    </button>
                  </div>
                </article>
              </li>
            ))}
          </ul>
        ) : (
          <div className="overflow-hidden rounded-card border border-border bg-surface">
            <table className="w-full border-collapse text-[var(--text-sm)]">
              <thead>
                <tr className="border-b border-border text-left text-ink-2">
                  <th className="px-4 py-2 font-medium">标题</th>
                  <th className="px-4 py-2 font-medium">版本</th>
                  <th className="px-4 py-2 font-medium">页数</th>
                  <th className="px-4 py-2 font-medium">来源</th>
                  <th className="px-4 py-2 font-medium">状态</th>
                </tr>
              </thead>
              <tbody>
                {documents.map((doc) => (
                  <tr key={doc.id} className="border-b border-border last:border-0 hover:bg-surface-2">
                    <td className="px-4 py-2 text-ink">{doc.title}</td>
                    <td className="px-4 py-2 text-ink-2">{doc.version ?? "—"}</td>
                    <td className="px-4 py-2 text-ink-2">{doc.page_count}</td>
                    <td className="px-4 py-2 text-ink-2">{SOURCE_LABEL[doc.source_kind ?? "vector"]}</td>
                    <td className={cn("px-4 py-2", STATUS_STYLE[doc.status])}>{STATUS_LABEL[doc.status]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {dragging && (
        <div className="pointer-events-none fixed inset-0 z-30 flex items-center justify-center bg-primary/10">
          <div className="rounded-dialog border-2 border-dashed border-primary bg-surface px-10 py-8 text-center shadow-lg">
            <Upload className="mx-auto size-8 text-primary" aria-hidden />
            <p className="mt-2 text-[var(--text-md)] font-medium text-ink">松开即可上传</p>
            <p className="text-[var(--text-sm)] text-ink-2">支持多文件，单文件 ≤ 200MB</p>
          </div>
        </div>
      )}
    </div>
  );
}
