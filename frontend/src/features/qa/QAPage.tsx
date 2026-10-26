import { ArrowUp, MessageSquareQuote, ShieldAlert } from "lucide-react";
import { useState } from "react";

import { Button } from "@/design/Button";
import { cn } from "@/lib/cn";
import { mockQA } from "@/mocks/data";

const PRESETS = ["作者与机构", "训练硬件是什么？", "超参数设置", "BLEU 分数"];

interface Turn {
  id: string;
  question: string;
  answer: string;
  citations: { marker: string; page: number; quote: string }[];
  refused: boolean;
}

export function QAPage() {
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [scope, setScope] = useState<"doc" | "set" | "all">("all");
  const [mode, setMode] = useState<"qa" | "compare">("qa");

  const ask = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    const hit =
      mockQA.find((item) => item.question === trimmed) ??
      mockQA.find((item) => !item.refused && trimmed.length > 0);
    setTurns((prev) => [
      ...prev,
      {
        id: crypto.randomUUID(),
        question: trimmed,
        answer: hit?.refused ? "" : (hit?.answer ?? "未在所选文献中找到依据。"),
        citations: hit?.citations ?? [],
        refused: hit?.refused ?? true,
      },
    ]);
    setQuestion("");
  };

  return (
    <div className="flex h-full min-h-0">
      <aside className="flex w-[220px] shrink-0 flex-col border-r border-border bg-surface">
        <div className="border-b border-border px-4 py-3 text-[var(--text-sm)] font-medium text-ink">历史会话</div>
        <div className="p-2">
          <Button variant="secondary" size="sm" className="w-full">
            新建会话
          </Button>
        </div>
        <p className="px-4 py-6 text-center text-[var(--text-sm)] text-ink-2">还没有历史会话</p>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col">
        <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border px-6 py-3">
          <div className="flex rounded-control border border-border p-0.5" role="group" aria-label="检索范围">
            {(
              [
                ["doc", "单篇"],
                ["set", "选集"],
                ["all", "全库"],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                aria-pressed={scope === key}
                onClick={() => {
                  setScope(key);
                }}
                className={cn(
                  "rounded-[6px] px-3 py-1 text-[var(--text-sm)]",
                  scope === key ? "bg-surface-2 font-medium text-ink" : "text-ink-2 hover:text-ink",
                )}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="flex rounded-control border border-border p-0.5" role="group" aria-label="模式">
            {(
              [
                ["qa", "问答"],
                ["compare", "对比"],
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
                  "rounded-[6px] px-3 py-1 text-[var(--text-sm)]",
                  mode === key ? "bg-surface-2 font-medium text-ink" : "text-ink-2 hover:text-ink",
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="app-scroll flex-1 px-6 py-5">
          {turns.length === 0 ? (
            <div className="mx-auto max-w-[720px] pt-10 text-center">
              <MessageSquareQuote className="mx-auto size-8 text-ink-2" strokeWidth={1.5} aria-hidden />
              <p className="mt-3 text-[var(--text-md)] font-medium text-ink">就你的文献提问</p>
              <p className="mt-1 text-[var(--text-sm)] text-ink-2">
                每条结论都会附原文锚点，点开即可定位到 PDF 中的对应位置。
              </p>
              <div className="mt-5 flex flex-wrap justify-center gap-2">
                {PRESETS.map((preset) => (
                  <button
                    key={preset}
                    type="button"
                    onClick={() => {
                      setQuestion(preset);
                    }}
                    className="rounded-full border border-border bg-surface px-3 py-1.5 text-[var(--text-sm)] text-ink-2 transition-colors hover:border-primary hover:text-primary"
                  >
                    {preset}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <ul className="mx-auto max-w-[760px] space-y-6">
              {turns.map((turn) => (
                <li key={turn.id} className="space-y-3">
                  <p className="ml-auto w-fit max-w-[80%] rounded-card bg-primary px-4 py-2 text-[var(--text-base)] text-white">
                    {turn.question}
                  </p>
                  {turn.refused ? (
                    <div className="rounded-card border border-border bg-surface-2 p-4">
                      <p className="flex items-center gap-2 text-[var(--text-base)] font-medium text-ink">
                        <ShieldAlert className="size-4 text-warn-text" aria-hidden />
                        未在所选文献中找到依据
                      </p>
                      <p className="mt-1 text-[var(--text-sm)] text-ink-2">
                        可以扩大检索范围，或换一种问法。
                      </p>
                    </div>
                  ) : (
                    <div className="rounded-card border border-border bg-surface p-4">
                      <p className="text-[var(--text-base)] leading-relaxed text-ink">{turn.answer}</p>
                      {turn.citations.length > 0 && (
                        <div className="mt-3 flex flex-wrap gap-2">
                          {turn.citations.map((citation) => (
                            <button
                              key={citation.marker}
                              type="button"
                              title={citation.quote}
                              className="rounded-full border border-border bg-surface-2 px-2.5 py-1 text-[var(--text-xs)] text-primary hover:border-primary"
                            >
                              {citation.marker} 第 {citation.page} 页
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        <form
          className="shrink-0 border-t border-border bg-surface px-6 py-3"
          onSubmit={(event) => {
            event.preventDefault();
            ask(question);
          }}
        >
          <div className="mx-auto flex max-w-[760px] items-end gap-2">
            <textarea
              value={question}
              onChange={(event) => {
                setQuestion(event.target.value);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  ask(question);
                }
              }}
              rows={2}
              placeholder="问点什么，例如：训练用了多少块什么型号的 GPU？"
              aria-label="提问"
              className="flex-1 resize-none rounded-control border border-border bg-surface-2 px-3 py-2 text-[var(--text-base)] text-ink outline-none placeholder:text-ink-2"
            />
            <Button type="submit" variant="primary" size="icon" aria-label="发送" disabled={!question.trim()}>
              <ArrowUp className="size-4" aria-hidden />
            </Button>
          </div>
        </form>
      </section>
    </div>
  );
}
