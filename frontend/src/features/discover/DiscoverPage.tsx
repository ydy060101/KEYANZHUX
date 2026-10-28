import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, Compass, Download, Search, Sparkles } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Button } from "@/design/Button";
import { EmptyState, ErrorState, Skeleton } from "@/design/States";
import { HitCard } from "@/features/discover/HitCard";
import { fetchRecommendations, searchPapers, sourceLabel } from "@/features/discover/api";
import { cn } from "@/lib/cn";

type Tab = "recommend" | "search" | "references";

const TABS = [
  ["recommend", "推荐流"],
  ["search", "搜索下载"],
  ["references", "参考文献导入"],
] as const;

/**
 * Discovery (T5.1/T5.6).
 *
 * The feed is computed by the backend from the library's own titles, and the
 * search queries the four sources live. Nothing on this page is a fixed list:
 * an empty library or an empty query shows an empty state, not sample rows
 * (H16).
 */
export function DiscoverPage() {
  const [tab, setTab] = useState<Tab>("recommend");
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");

  const feed = useQuery({
    queryKey: ["recommendations"],
    queryFn: () => fetchRecommendations(12),
    enabled: tab === "recommend",
    staleTime: 5 * 60 * 1000,
  });
  const search = useMutation({ mutationFn: (value: string) => searchPapers(value, 10) });

  const runSearch = () => {
    const value = query.trim();
    if (!value) return;
    setSubmitted(value);
    search.mutate(value);
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center gap-1 border-b border-border px-6">
        {TABS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            onClick={() => {
              setTab(key);
            }}
            className={cn(
              "px-3 py-3 text-[var(--text-base)]",
              tab === key ? "border-b-2 border-primary font-medium text-primary" : "text-ink-2 hover:text-ink",
            )}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="app-scroll flex-1 px-6 py-5">
        {tab === "recommend" && (
          <div className="mx-auto max-w-[1000px]">
            <div className="mb-4 flex items-center gap-2 text-[var(--text-sm)] text-ink-2">
              <Sparkles className="size-4" aria-hidden />
              依据库中最近三篇文献的标题检索 arXiv；分数是标题关键词的重合度。
            </div>
            {feed.isPending && <FeedSkeleton />}
            {feed.isError && (
              <ErrorState
                message="推荐加载失败"
                detail={feed.error instanceof Error ? feed.error.message : undefined}
                onRetry={() => {
                  void feed.refetch();
                }}
              />
            )}
            {feed.isSuccess && feed.data.length === 0 && (
              <EmptyState
                title="还没有可推荐的文献"
                description="先导入至少一篇有标题的文献，推荐流会用它的标题去检索相关论文。"
                icon={<Compass className="size-6" aria-hidden />}
                action={
                  <Link to="/library" className="text-[var(--text-sm)] font-medium text-primary hover:underline">
                    去文献库上传
                  </Link>
                }
              />
            )}
            {feed.isSuccess && feed.data.length > 0 && (
              <ul className="grid grid-cols-[repeat(auto-fill,minmax(320px,1fr))] gap-4">
                {feed.data.map((row) => (
                  <li key={`${row.source}:${row.paper_id}`}>
                    <HitCard
                      title={row.title}
                      source={row.source}
                      extId={row.paper_id}
                      authors={row.authors}
                      year={row.year}
                      abstract={row.abstract}
                      pdfUrl={row.pdf_url}
                      score={row.score}
                      reasons={row.reasons}
                    />
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {tab === "search" && (
          <div className="mx-auto max-w-[1000px]">
            <div className="flex items-center gap-2">
              <div className="flex h-10 flex-1 items-center gap-2 rounded-control border border-border bg-surface px-3">
                <Search className="size-4 text-ink-2" strokeWidth={1.75} aria-hidden />
                <input
                  value={query}
                  onChange={(event) => {
                    setQuery(event.target.value);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") runSearch();
                  }}
                  placeholder="输入论文标题、关键词、arXiv ID 或 DOI"
                  aria-label="搜索论文"
                  data-testid="discover-query"
                  className="w-full bg-transparent text-[var(--text-base)] outline-none placeholder:text-ink-2"
                />
              </div>
              <Button
                variant="primary"
                data-testid="discover-search"
                loading={search.isPending}
                onClick={runSearch}
                disabled={!query.trim()}
              >
                搜索
              </Button>
            </div>

            <div className="mt-6">
              {!submitted && !search.isPending && (
                <EmptyState
                  title="输入关键词开始检索"
                  description="会同时查询 arXiv、Semantic Scholar、OpenAlex 与 Crossref，并标注是否已在库中。"
                  icon={<Download className="size-6" aria-hidden />}
                />
              )}
              {search.isPending && <FeedSkeleton />}
              {search.isError && (
                <ErrorState
                  message="检索失败"
                  detail={search.error instanceof Error ? search.error.message : undefined}
                  onRetry={runSearch}
                />
              )}
              {search.isSuccess && search.data.degraded.length > 0 && (
                <p
                  data-testid="discover-degraded"
                  className="mb-3 flex items-start gap-2 rounded-control border border-warn bg-surface px-3 py-2 text-[var(--text-sm)] text-ink"
                >
                  <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
                  部分来源暂时不可用：{search.data.degraded.map(sourceLabel).join("、")}；以下结果来自其余来源。
                </p>
              )}
              {search.isSuccess && search.data.hits.length === 0 && (
                <EmptyState
                  title="没有找到相关论文"
                  description={`“${submitted}”在四个来源中都没有结果，试试更短的关键词或 arXiv ID。`}
                />
              )}
              {search.isSuccess && search.data.hits.length > 0 && (
                <>
                  <p className="mb-3 text-[var(--text-sm)] text-ink-2" data-testid="discover-count">
                    {search.data.hits.length} 条结果
                  </p>
                  <ul className="grid grid-cols-[repeat(auto-fill,minmax(320px,1fr))] gap-4">
                    {search.data.hits.map((hit) => (
                      <li key={`${hit.source}:${hit.ext_id}:${hit.title}`}>
                        <HitCard
                          title={hit.title}
                          source={hit.source}
                          extId={hit.ext_id}
                          authors={hit.authors}
                          year={hit.year}
                          abstract={hit.abstract}
                          pdfUrl={hit.pdf_url}
                          inLibrary={hit.in_library}
                        />
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          </div>
        )}

        {tab === "references" && (
          <EmptyState
            title="参考文献批量导入尚未接入"
            description="该流程在 T5.2 实现：会按含金量打分剔除应付式引用，每条给出理由后再入库。"
            icon={<Compass className="size-6" aria-hidden />}
          />
        )}
      </div>
    </div>
  );
}

function FeedSkeleton() {
  return (
    <ul className="grid grid-cols-[repeat(auto-fill,minmax(320px,1fr))] gap-4" aria-busy>
      {Array.from({ length: 6 }, (_, index) => (
        <li key={index} className="space-y-2 rounded-card border border-border bg-surface p-4">
          <Skeleton className="h-5 w-4/5" />
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-16 w-full" />
        </li>
      ))}
    </ul>
  );
}
