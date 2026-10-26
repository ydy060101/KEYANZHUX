import { CheckCircle2, CircleAlert, FileText, Play, Upload } from "lucide-react";
import { useState } from "react";

import { Button } from "@/design/Button";
import { EmptyState } from "@/design/States";
import { cn } from "@/lib/cn";

type Workspace = "outline" | "figures" | "data" | "translate";

const REFERENCES = [
  { title: "Attention Is All You Need", status: "verified" as const, source: "arXiv:1706.03762" },
  { title: "BERT: Pre-training of Deep Bidirectional Transformers", status: "verified" as const, source: "arXiv:1810.04805" },
  { title: "Language Models are Few-Shot Learners", status: "verified" as const, source: "arXiv:2005.14165" },
  { title: "Unverified candidate", status: "unverified" as const, source: null },
];

export function WritingPage() {
  const [workspace, setWorkspace] = useState<Workspace>("outline");
  const [idea, setIdea] = useState("");

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center gap-1 border-b border-border px-6">
        {(
          [
            ["outline", "论文框架"],
            ["figures", "图表工坊"],
            ["data", "数据工坊"],
            ["translate", "学术翻译"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={workspace === key}
            onClick={() => {
              setWorkspace(key);
            }}
            className={cn(
              "px-3 py-3 text-[var(--text-base)]",
              workspace === key ? "border-b-2 border-primary font-medium text-primary" : "text-ink-2 hover:text-ink",
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {workspace === "outline" && (
        <div className="flex min-h-0 flex-1">
          <aside className="flex w-[300px] shrink-0 flex-col gap-3 border-r border-border p-4">
            <label htmlFor="idea" className="text-[var(--text-sm)] font-medium text-ink">
              研究想法
            </label>
            <textarea
              id="idea"
              value={idea}
              onChange={(event) => {
                setIdea(event.target.value);
              }}
              rows={8}
              placeholder="例如：一种在长文档上做检索增强问答、并对每条结论强制溯源的方法。"
              className="resize-none rounded-control border border-border bg-surface-2 px-3 py-2 text-[var(--text-base)] text-ink outline-none placeholder:text-ink-2"
            />
            <Button variant="primary" disabled={!idea.trim()}>
              生成框架
            </Button>
          </aside>

          <section className="app-scroll min-w-0 flex-1 p-6">
            {idea.trim() ? (
              <article className="mx-auto max-w-[var(--measure)] space-y-4 font-read">
                <h2 className="text-[var(--text-lg)] font-semibold">Abstract</h2>
                <p className="text-[var(--text-base)] leading-relaxed text-ink-2">
                  生成后在此显示正文。引用以 <code className="font-mono text-[var(--text-sm)]">\cite&#123;key&#125;</code>{" "}
                  形式出现，点击可定位到右侧校验面板。
                </p>
              </article>
            ) : (
              <EmptyState
                title="输入一个想法"
                description="会先检索库内与外部文献，再生成框架；参考文献全部来自真实检索结果。"
                icon={<FileText className="size-6" aria-hidden />}
              />
            )}
          </section>

          <aside className="flex w-[280px] shrink-0 flex-col border-l border-border p-4">
            <h2 className="mb-2 text-[var(--text-sm)] font-medium text-ink">参考文献校验</h2>
            <ul className="space-y-2">
              {REFERENCES.map((ref) => (
                <li key={ref.title} className="rounded-control border border-border p-2">
                  <p className="flex items-start gap-1.5 text-[var(--text-sm)] text-ink">
                    {ref.status === "verified" ? (
                      <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-success-text" aria-hidden />
                    ) : (
                      <CircleAlert className="mt-0.5 size-3.5 shrink-0 text-warn-text" aria-hidden />
                    )}
                    <span className="line-clamp-2">{ref.title}</span>
                  </p>
                  <p className="mt-1 text-[var(--text-xs)] text-ink-2">{ref.source ?? "[待补充]"}</p>
                </li>
              ))}
            </ul>
            <Button size="sm" variant="secondary" className="mt-auto">
              导出 BibTeX
            </Button>
          </aside>
        </div>
      )}

      {workspace === "figures" && (
        <div className="flex min-h-0 flex-1">
          <aside className="flex w-[280px] shrink-0 flex-col gap-3 border-r border-border p-4">
            <label htmlFor="figure-desc" className="text-[var(--text-sm)] font-medium text-ink">
              描述需求
            </label>
            <textarea
              id="figure-desc"
              rows={6}
              placeholder="例如：画一个 Transformer 编码器-解码器结构图。"
              className="resize-none rounded-control border border-border bg-surface-2 px-3 py-2 text-[var(--text-base)] outline-none placeholder:text-ink-2"
            />
            <select aria-label="图形类型" className="h-9 rounded-control border border-border bg-surface px-2 text-[var(--text-sm)]">
              <option>Mermaid</option>
              <option>Graphviz</option>
              <option>TikZ</option>
              <option>Matplotlib</option>
            </select>
            <Button variant="primary">
              <Play className="size-4" aria-hidden />
              生成并运行
            </Button>
          </aside>
          <section className="flex min-w-0 flex-1 flex-col">
            <div className="flex-1 border-b border-border bg-surface-2 p-6">
              <EmptyState title="还没有脚本" description="生成后会在此显示脚本与实时预览。" />
            </div>
            <div className="h-[240px] shrink-0 bg-surface p-4 font-mono text-[var(--text-sm)] text-ink-2">
              <p>// 脚本编辑器</p>
            </div>
          </section>
        </div>
      )}

      {workspace === "data" && (
        <div className="app-scroll flex-1 p-6">
          <EmptyState
            title="上传一份 CSV"
            description="解析后会推断列类型并建议图表；图注由统计量生成，数字可逐项核对。"
            icon={<Upload className="size-6" aria-hidden />}
          />
        </div>
      )}

      {workspace === "translate" && (
        <div className="flex min-h-0 flex-1">
          <div className="flex min-w-0 flex-1 flex-col border-r border-border">
            <div className="border-b border-border px-4 py-2 text-[var(--text-sm)] font-medium text-ink">中文</div>
            <textarea
              aria-label="中文原文"
              className="app-scroll flex-1 resize-none bg-surface p-4 font-read text-[var(--text-base)] leading-relaxed outline-none"
              placeholder="粘贴中文摘要或正文…"
            />
          </div>
          <div className="flex min-w-0 flex-1 flex-col">
            <div className="border-b border-border px-4 py-2 text-[var(--text-sm)] font-medium text-ink">English</div>
            <textarea
              aria-label="英文译文"
              className="app-scroll flex-1 resize-none bg-surface-2 p-4 font-read text-[var(--text-base)] leading-relaxed outline-none"
              placeholder="译文会显示在这里"
            />
          </div>
        </div>
      )}
    </div>
  );
}
