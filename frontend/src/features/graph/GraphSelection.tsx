import { useMutation } from "@tanstack/react-query";
import { GitFork, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Button } from "@/design/Button";
import { EmptyState, ErrorState, Skeleton } from "@/design/States";
import { createGraph } from "@/features/graph/api";
import { useDocuments } from "@/features/library/api";
import { useJobStream } from "@/features/library/jobs";

function graphIdOf(result: unknown): string | null {
  if (typeof result !== "object" || result === null) return null;
  const value = (result as Record<string, unknown>).graph_id;
  return typeof value === "string" ? value : null;
}

/** Step one of 02 §4.5: choose the documents, then follow the build job. */
export function GraphSelection() {
  const navigate = useNavigate();
  const documentsQuery = useDocuments({ query: "", status: "", tag: "" });
  const [selected, setSelected] = useState<string[]>([]);
  const [filter, setFilter] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: createGraph,
    onSuccess: (job) => {
      setJobId(job.id);
    },
  });
  const job = useJobStream(jobId, "构建引用图");

  const succeeded = job.data?.status === "succeeded";
  useEffect(() => {
    const graphId = graphIdOf(job.data?.result);
    if (succeeded && graphId) navigate(`/graph/${graphId}`);
  }, [succeeded, job.data, navigate]);

  const documents = documentsQuery.data?.items ?? [];
  const needle = filter.trim().toLowerCase();
  const shown = documents.filter(
    (doc) => !needle || doc.title.toLowerCase().includes(needle) || (doc.arxiv_id ?? "").includes(needle),
  );
  const readyCount = documents.filter((doc) => doc.status === "ready").length;

  const toggle = (id: string) => {
    setSelected((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
    );
  };

  const running = job.data ? ["queued", "running"].includes(job.data.status) : mutation.isPending;
  const failed = job.data?.status === "failed" || job.data?.status === "cancelled";

  return (
    <div className="app-scroll h-full px-6 py-6">
      <div className="mx-auto max-w-[880px]">
        <header className="mb-5">
          <h1 className="text-[var(--text-xl)] font-semibold text-ink">引用图谱</h1>
          <p className="mt-1 text-[var(--text-sm)] text-ink-2">
            选择至少两篇已解析文献。引用按 DOI → arXiv ID → 标题（相似度 ≥ 0.92 且年份一致）匹配，未匹配的参考文献不进入图。
          </p>
        </header>

        {documentsQuery.isPending && (
          <div className="space-y-2" aria-busy>
            {Array.from({ length: 5 }, (_, index) => (
              <Skeleton key={index} className="h-14 w-full" />
            ))}
          </div>
        )}
        {documentsQuery.isError && (
          <ErrorState
            message="文献库加载失败"
            detail={documentsQuery.error instanceof Error ? documentsQuery.error.message : undefined}
            onRetry={() => {
              void documentsQuery.refetch();
            }}
          />
        )}
        {documentsQuery.isSuccess && documents.length === 0 && (
          <EmptyState
            title="文献库还是空的"
            description="先上传并解析文献，之后才能把它们之间的引用关系画出来。"
            icon={<GitFork className="size-6" aria-hidden />}
            action={
              <Link to="/library" className="text-[var(--text-sm)] font-medium text-primary hover:underline">
                去文献库上传
              </Link>
            }
          />
        )}
        {documentsQuery.isSuccess && documents.length > 0 && (
          <>
            <div className="mb-3 flex items-center gap-2">
              <div className="flex h-10 flex-1 items-center gap-2 rounded-control border border-border bg-surface px-3">
                <Search className="size-4 text-ink-2" strokeWidth={1.75} aria-hidden />
                <input
                  value={filter}
                  onChange={(event) => {
                    setFilter(event.target.value);
                  }}
                  placeholder="按标题或 arXiv ID 过滤"
                  aria-label="过滤文献"
                  data-testid="graph-filter"
                  className="w-full bg-transparent text-[var(--text-base)] outline-none placeholder:text-ink-2"
                />
              </div>
              <span className="shrink-0 text-[var(--text-sm)] text-ink-2">
                {readyCount} 篇可建图 · 已选 {selected.length}
              </span>
            </div>

            <ul className="space-y-2">
              {shown.map((doc) => {
                const ready = doc.status === "ready";
                const checked = selected.includes(doc.id);
                return (
                  <li key={doc.id}>
                    <label
                      className={
                        ready
                          ? "flex cursor-pointer items-center gap-3 rounded-card border border-border bg-surface px-4 py-3 hover:border-primary"
                          : "flex cursor-not-allowed items-center gap-3 rounded-card border border-border bg-surface-2 px-4 py-3 opacity-70"
                      }
                    >
                      <input
                        type="checkbox"
                        className="size-4 accent-[var(--primary)]"
                        checked={checked}
                        disabled={!ready || running}
                        onChange={() => {
                          toggle(doc.id);
                        }}
                        data-testid="graph-doc"
                        data-doc-id={doc.id}
                        aria-label={doc.title}
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[var(--text-base)] text-ink">{doc.title}</span>
                        <span className="mt-0.5 block text-[var(--text-xs)] text-ink-2">
                          {doc.arxiv_id ?? "无 arXiv ID"} · {doc.page_count} 页 ·{" "}
                          {ready ? `${doc.stats?.references ?? 0} 条参考文献` : "解析完成后可选"}
                        </span>
                      </span>
                    </label>
                  </li>
                );
              })}
            </ul>
            {shown.length === 0 && (
              <p className="py-8 text-center text-[var(--text-sm)] text-ink-2">没有匹配“{filter}”的文献。</p>
            )}

            <div className="sticky bottom-0 mt-5 flex items-center gap-3 border-t border-border bg-bg py-4">
              <Button
                variant="primary"
                data-testid="graph-build"
                disabled={selected.length < 2 || running}
                loading={mutation.isPending}
                onClick={() => {
                  mutation.mutate(selected);
                }}
              >
                生成引用图
              </Button>
              <span className="text-[var(--text-sm)] text-ink-2">
                {selected.length < 2 ? "至少选择两篇已解析文献" : `将分析 ${selected.length} 篇文献的参考文献`}
              </span>
            </div>

            {running && job.data && (
              <div className="mt-2 rounded-card border border-border bg-surface p-4" data-testid="graph-job">
                <div className="flex items-center justify-between text-[var(--text-sm)]">
                  <span className="text-ink">{job.data.stage || "排队中"}</span>
                  <span className="text-ink-2">{Math.round(job.data.progress * 100)}%</span>
                </div>
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-2">
                  <div
                    className="h-full rounded-full bg-primary transition-[width] duration-200"
                    style={{ width: `${String(Math.round(job.data.progress * 100))}%` }}
                  />
                </div>
              </div>
            )}
            {failed && (
              <p className="mt-2 rounded-control border border-danger bg-surface px-3 py-2 text-[var(--text-sm)] text-danger-text" data-testid="graph-job-error">
                {job.data?.error ?? "建图任务失败"}
                <button
                  type="button"
                  className="ml-2 font-medium underline"
                  onClick={() => {
                    setJobId(null);
                    mutation.reset();
                  }}
                >
                  重试
                </button>
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
