import { Code2, Download, Search, Star, ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";

import { Button } from "@/design/Button";
import { EmptyState } from "@/design/States";
import { cn } from "@/lib/cn";

interface Recommendation {
  id: string;
  title: string;
  authors: string;
  year: number;
  abstract: string;
  reasons: string[];
  github?: string;
  stars?: number;
  score: number;
}

const RECOMMENDATIONS: Recommendation[] = [
  {
    id: "p1",
    title: "RoFormer: Enhanced Transformer with Rotary Position Embedding",
    authors: "Jianlin Su, Yu Lu, Shengfeng Pan",
    year: 2021,
    abstract:
      "We propose a novel method to encode position information with a rotation matrix, which brings clear improvement in long-text understanding.",
    reasons: ["与你库中《Attention Is All You Need》相似度 0.81", "附带开源代码，⭐2.4k", "3 天前更新"],
    github: "https://github.com/ZhuiyiTechnology/roformer",
    stars: 2400,
    score: 0.86,
  },
  {
    id: "p2",
    title: "Scaling Laws for Neural Language Models",
    authors: "Jared Kaplan, Sam McCandlish, Tom Henighan",
    year: 2020,
    abstract:
      "We study empirical scaling laws for language model performance on the cross-entropy loss, finding power-law relationships.",
    reasons: ["与你库中《Language Models are Few-Shot Learners》相似度 0.79", "被库内 2 篇论文引用"],
    score: 0.74,
  },
  {
    id: "p3",
    title: "FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness",
    authors: "Tri Dao, Daniel Y. Fu, Stefano Ermon",
    year: 2022,
    abstract: "We propose FlashAttention, an IO-aware exact attention algorithm that uses tiling to reduce memory reads/writes.",
    reasons: ["与你库中《Attention Is All You Need》相似度 0.72", "附带开源代码，⭐5.8k"],
    github: "https://github.com/Dao-AILab/flash-attention",
    stars: 5800,
    score: 0.71,
  },
];

type Tab = "recommend" | "search" | "references";

export function DiscoverPage() {
  const [tab, setTab] = useState<Tab>("recommend");
  const [voted, setVoted] = useState<Record<string, 1 | -1>>({});
  const [query, setQuery] = useState("");

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center gap-1 border-b border-border px-6">
        {(
          [
            ["recommend", "推荐流"],
            ["search", "搜索下载"],
            ["references", "参考文献导入"],
          ] as const
        ).map(([key, label]) => (
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
          <ul className="mx-auto grid max-w-[1000px] grid-cols-[repeat(auto-fill,minmax(320px,1fr))] gap-4">
            {RECOMMENDATIONS.filter((item) => voted[item.id] !== -1).map((item) => (
              <li key={item.id}>
                <article className="flex h-full flex-col gap-2 rounded-card border border-border bg-surface p-4">
                  <h3 className="text-[var(--text-base)] font-medium leading-snug text-ink">{item.title}</h3>
                  <p className="text-[var(--text-sm)] text-ink-2">
                    {item.authors} · {item.year}
                  </p>
                  <p className="line-clamp-3 text-[var(--text-sm)] leading-relaxed text-ink-2">{item.abstract}</p>
                  <ul className="flex flex-wrap gap-1.5">
                    {item.reasons.map((reason) => (
                      <li
                        key={reason}
                        className="rounded-full bg-surface-2 px-2 py-0.5 text-[var(--text-xs)] text-ink-2"
                      >
                        {reason}
                      </li>
                    ))}
                  </ul>
                  {item.github && (
                    <a
                      href={item.github}
                      target="_blank"
                      rel="noreferrer"
                      className="flex items-center gap-1.5 text-[var(--text-sm)] text-primary hover:underline"
                    >
                      <Code2 className="size-3.5" aria-hidden />
                      <Star className="size-3.5" aria-hidden />
                      {item.stars?.toLocaleString()}
                    </a>
                  )}
                  <div className="mt-auto flex items-center gap-1 pt-2">
                    <Button size="sm" variant="secondary">
                      入库
                    </Button>
                    <button
                      type="button"
                      aria-label="有用"
                      onClick={() => {
                        setVoted((prev) => ({ ...prev, [item.id]: 1 }));
                      }}
                      className={cn(
                        "ml-auto rounded p-1.5 hover:bg-surface-2",
                        voted[item.id] === 1 ? "text-success-text" : "text-ink-2",
                      )}
                    >
                      <ThumbsUp className="size-4" aria-hidden />
                    </button>
                    <button
                      type="button"
                      aria-label="不感兴趣"
                      onClick={() => {
                        setVoted((prev) => ({ ...prev, [item.id]: -1 }));
                      }}
                      className={cn(
                        "rounded p-1.5 hover:bg-surface-2",
                        voted[item.id] === -1 ? "text-danger-text" : "text-ink-2",
                      )}
                    >
                      <ThumbsDown className="size-4" aria-hidden />
                    </button>
                  </div>
                </article>
              </li>
            ))}
          </ul>
        )}

        {tab === "search" && (
          <div className="mx-auto max-w-[760px]">
            <div className="flex items-center gap-2">
              <div className="flex h-10 flex-1 items-center gap-2 rounded-control border border-border bg-surface px-3">
                <Search className="size-4 text-ink-2" strokeWidth={1.75} aria-hidden />
                <input
                  value={query}
                  onChange={(event) => {
                    setQuery(event.target.value);
                  }}
                  placeholder="输入论文标题、arXiv ID 或 DOI"
                  aria-label="搜索论文"
                  className="w-full bg-transparent text-[var(--text-base)] outline-none placeholder:text-ink-2"
                />
              </div>
              <Button variant="primary">搜索</Button>
            </div>
            <div className="mt-6">
              <EmptyState
                title="输入关键词开始检索"
                description="会同时查询 arXiv、Semantic Scholar 与 OpenAlex，并标注是否已在库中。"
                icon={<Download className="size-6" aria-hidden />}
              />
            </div>
          </div>
        )}

        {tab === "references" && (
          <EmptyState
            title="选择一篇文献"
            description="导入它的参考文献时，会按含金量自动剔除应付式引用，每条都给出理由。"
          />
        )}
      </div>
    </div>
  );
}
