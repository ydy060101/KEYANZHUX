import { CheckCircle2, FileText, Loader2, Sparkles } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { Button } from "@/design/Button";
import { EmptyState, ErrorState, Skeleton } from "@/design/States";
import { cn } from "@/lib/cn";
import {
  citationKeys,
  streamOutline,
  type OutlineFlag,
  type OutlineResult,
  type WritingReference,
} from "./api";
import { MarkdownPreview } from "./Markdown";
import { ReferencePanel } from "./ReferencePanel";

type Status = "idle" | "streaming" | "done" | "error";

interface Stage {
  stage: string;
  message: string;
  count: number | null;
}

const STEPS = [
  { key: "planning", label: "生成结构" },
  { key: "searching", label: "检索文献" },
  { key: "verifying", label: "核验文献" },
  { key: "writing", label: "撰写正文" },
] as const;

interface DraftState {
  result: OutlineResult;
  references: WritingReference[];
  flags: OutlineFlag[];
  markdown: string;
}

export function OutlineWorkspace() {
  const [idea, setIdea] = useState("");
  const [language, setLanguage] = useState<"zh" | "en">("zh");
  const [status, setStatus] = useState<Status>("idle");
  const [stages, setStages] = useState<Stage[]>([]);
  const [draft, setDraft] = useState<DraftState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"preview" | "edit">("preview");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const usedKeys = useMemo(() => citationKeys(draft?.markdown ?? ""), [draft?.markdown]);
  const active = stages.at(-1)?.stage ?? null;
  const activeIndex = active === null ? -1 : STEPS.findIndex((step) => step.key === active);

  const generate = () => {
    const value = idea.trim();
    if (!value) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setStatus("streaming");
    setStages([]);
    setError(null);
    setDraft(null);
    setSelectedKey(null);
    setMode("preview");

    void streamOutline(
      { idea: value, language },
      (event) => {
        if (event.type === "stage") {
          setStages((current) => [...current.filter((item) => item.stage !== event.stage), { stage: event.stage, message: event.message, count: event.count }]);
          return;
        }
        if (event.type === "done") {
          setDraft({
            result: event.data,
            references: event.data.references,
            flags: event.data.flags,
            markdown: event.data.markdown,
          });
          setStatus("done");
          return;
        }
        setError(event.message);
        setStatus("error");
      },
      controller.signal,
    ).catch((reason: unknown) => {
      if (controller.signal.aborted) return;
      setError(reason instanceof Error ? reason.message : "框架生成失败");
      setStatus("error");
    });
  };

  return (
    <div className="flex min-h-0 flex-1" data-testid="writing-outline">
      <aside className="flex w-[280px] shrink-0 flex-col gap-3 border-r border-border bg-surface p-4">
        <label htmlFor="writing-idea" className="text-[var(--text-sm)] font-medium text-ink">
          研究想法
        </label>
        <textarea
          id="writing-idea"
          value={idea}
          onChange={(event) => {
            setIdea(event.target.value);
          }}
          rows={9}
          maxLength={4000}
          placeholder="例如：一种在长文档上做检索增强问答、并对每条结论强制溯源的方法。"
          data-testid="writing-idea"
          className="resize-none rounded-control border border-border bg-surface-2 px-3 py-2 text-[var(--text-base)] leading-relaxed text-ink outline-none placeholder:text-ink-2 focus:border-primary"
        />
        <div className="flex items-center justify-between text-[var(--text-xs)] text-ink-2">
          <span>{idea.length} / 4000</span>
          <div className="flex rounded-control border border-border p-0.5" role="group" aria-label="框架语言">
            {(["zh", "en"] as const).map((key) => (
              <button
                key={key}
                type="button"
                aria-pressed={language === key}
                onClick={() => {
                  setLanguage(key);
                }}
                className={cn(
                  "rounded-[6px] px-2 py-0.5 transition-colors duration-[--dur-fast]",
                  language === key ? "bg-primary text-white" : "text-ink-2 hover:text-ink",
                )}
              >
                {key === "zh" ? "中文" : "English"}
              </button>
            ))}
          </div>
        </div>
        <Button
          variant="primary"
          data-testid="writing-generate"
          disabled={!idea.trim() || status === "streaming"}
          loading={status === "streaming"}
          onClick={generate}
        >
          <Sparkles className="size-4" aria-hidden />
          {status === "streaming" ? "生成中…" : "生成框架"}
        </Button>

        <div className="mt-2 border-t border-border pt-3">
          <p className="text-[var(--text-xs)] font-medium text-ink">流程</p>
          <ol className="mt-2 space-y-2" data-testid="writing-stages">
            {STEPS.map((step, index) => {
              const reached = stages.some((item) => item.stage === step.key);
              const finished = status === "done" || (activeIndex >= 0 && index < activeIndex);
              const running = status === "streaming" && active === step.key;
              return (
                <li key={step.key} className="flex items-center gap-2 text-[var(--text-xs)]">
                  {finished ? (
                    <CheckCircle2 className="size-3.5 text-success-text" aria-hidden />
                  ) : running ? (
                    <Loader2 className="size-3.5 animate-spin text-primary" aria-hidden />
                  ) : (
                    <span
                      className={cn(
                        "size-3.5 rounded-full border",
                        reached ? "border-primary bg-primary/20" : "border-border bg-surface-2",
                      )}
                      aria-hidden
                    />
                  )}
                  <span className={finished || running ? "text-ink" : "text-ink-2"}>{step.label}</span>
                </li>
              );
            })}
          </ol>
          {status === "streaming" && stages.at(-1) && (
            <p className="mt-2 text-[11px] leading-relaxed text-ink-2" data-testid="writing-stage-message">
              {stages.at(-1)?.message}
              {stages.at(-1)?.count != null ? `（${String(stages.at(-1)?.count)} 篇）` : ""}
            </p>
          )}
        </div>
        <p className="mt-auto text-[11px] leading-relaxed text-ink-2">
          文献来自 arXiv、Crossref、OpenAlex 与 Semantic Scholar 的真实检索；未通过核验的候选不会写入引用（H02）。
        </p>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col bg-bg">
        {status === "idle" && !draft && (
          <div className="flex h-full items-center justify-center">
            <EmptyState
              title="输入一个研究想法"
              description="先生成 Abstract / Introduction / Related Work 框架，再逐条核验参考文献。正文中的引用可点击定位。"
              icon={<FileText className="size-6" aria-hidden />}
            />
          </div>
        )}

        {status === "streaming" && (
          <div className="app-scroll h-full p-6" aria-busy>
            <div className="mx-auto max-w-[var(--measure)] space-y-3">
              <Skeleton className="h-7 w-1/2" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-11/12" />
              <Skeleton className="h-4 w-4/5" />
              <Skeleton className="mt-8 h-6 w-1/3" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-10/12" />
            </div>
          </div>
        )}

        {status === "error" && (
          <div className="flex h-full items-center justify-center">
            <ErrorState
              message="框架生成失败"
              detail={error ?? "请稍后重试"}
              onRetry={() => {
                generate();
              }}
            />
          </div>
        )}

        {draft && status === "done" && (
          <>
            <header className="flex h-11 shrink-0 items-center gap-2 border-b border-border bg-surface px-4">
              <h2 className="min-w-0 truncate text-[var(--text-sm)] font-medium text-ink" title={draft.result.title}>
                {draft.result.title}
              </h2>
              <span className="shrink-0 text-[var(--text-xs)] text-ink-2">{draft.references.length} 篇已验证文献</span>
              <div className="ml-auto flex rounded-control border border-border p-0.5" role="group" aria-label="正文视图">
                {(
                  [
                    ["preview", "KaTeX 预览"],
                    ["edit", "编辑 Markdown"],
                  ] as const
                ).map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    aria-pressed={mode === key}
                    onClick={() => {
                      setMode(key);
                    }}
                    className={cn(
                      "rounded-[6px] px-2 py-1 text-[var(--text-xs)] transition-colors duration-[--dur-fast]",
                      mode === key ? "bg-primary text-white" : "text-ink-2 hover:text-ink",
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </header>
            {mode === "edit" ? (
              <textarea
                value={draft.markdown}
                aria-label="Markdown 源文"
                data-testid="writing-markdown"
                onChange={(event) => {
                  setDraft({ ...draft, markdown: event.target.value });
                }}
                spellCheck={false}
                className="app-scroll min-h-0 flex-1 resize-none bg-surface px-6 py-5 font-mono text-[var(--text-sm)] leading-relaxed text-ink outline-none"
              />
            ) : (
              <div className="app-scroll min-h-0 flex-1 px-6 py-5">
                <div className="mx-auto max-w-[var(--measure)] font-read">
                  <MarkdownPreview markdown={draft.markdown} selectedKey={selectedKey} onCite={setSelectedKey} />
                </div>
              </div>
            )}
          </>
        )}

        {draft && status !== "done" && (
          <div className="flex h-full items-center justify-center">
            <Skeleton className="h-48 w-2/3" />
          </div>
        )}
      </section>

      <ReferencePanel
        references={draft?.references ?? []}
        flags={draft?.flags ?? []}
        usedKeys={usedKeys}
        selectedKey={selectedKey}
        draftId={draft?.result.draftId ?? null}
        onSelect={(key) => {
          setSelectedKey(key);
          if (key) setMode("preview");
        }}
      />
    </div>
  );
}
