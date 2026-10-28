import { AlertTriangle, ArrowUp, MessageSquareQuote, ShieldAlert, Square } from "lucide-react";
import { Fragment, useEffect, useRef, useState } from "react";

import { Button } from "@/design/Button";
import { Skeleton } from "@/design/States";
import { cn } from "@/lib/cn";
import { AnchorChip } from "./AnchorChip";
import { CompareAnswer } from "./CompareTable";
import type { QaAnchor, QaCitation, QaFlag, QaMode, QaScope, QaTurn } from "./api";
import { useQaStream } from "./useQaStream";

const PRESETS = ["作者与机构", "训练硬件是什么？", "超参数设置", "这篇论文的主要贡献是什么？"];

export interface QaChatProps {
  scope: QaScope;
  mode: QaMode;
  docTitles: Record<string, string>;
  onOpenAnchor: (anchor: QaAnchor) => void;
  initialTurns?: QaTurn[];
  onTurnsChange?: (turns: QaTurn[]) => void;
  compact?: boolean;
  /** A reason the composer must stay disabled, from the page's own state. */
  disabledReason?: string;
}

/**
 * The shared QA conversation (02 §4.3/§4.2).
 *
 * `/qa` and the reader's right rail render this same component; the only
 * difference is width and whether completed turns are written to history. A
 * streamed sentence is appended as it arrives, and its anchor chips are
 * matched to the markers in the text, so a claim and its source never drift
 * apart.
 */
export function QaChat({
  scope,
  mode,
  docTitles,
  onOpenAnchor,
  initialTurns = [],
  onTurnsChange,
  compact = false,
  disabledReason,
}: QaChatProps) {
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const missingDocs = scope.type !== "all" && scope.doc_ids.length === 0;
  const tooFewForCompare =
    mode === "compare" && scope.type !== "all" && scope.doc_ids.length === 1;
  const blocked =
    disabledReason ??
    (missingDocs ? "请先选择文献" : tooFewForCompare ? "对比至少需要两篇文献" : null);

  const { turns, streaming, ask, stop } = useQaStream({
    scope,
    mode,
    blocked: Boolean(blocked),
    initialTurns,
    ...(onTurnsChange ? { onTurnsChange } : {}),
  });

  useEffect(() => {
    const node = scrollRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [turns]);

  const submit = () => {
    if (!draft.trim() || streaming || blocked) return;
    ask(draft);
    setDraft("");
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div
        ref={scrollRef}
        className={cn("app-scroll min-h-0 flex-1", compact ? "px-3 py-3" : "px-6 py-5")}
        data-testid="qa-scroll"
      >
        {turns.length === 0 ? (
          <EmptyPrompt
            compact={compact}
            onPreset={(preset) => {
              setDraft(preset);
            }}
          />
        ) : (
          <ul className={cn("mx-auto space-y-5", compact ? "max-w-none" : "max-w-[780px]")}>
            {turns.map((turn) => (
              <TurnView
                key={turn.id}
                turn={turn}
                docTitles={docTitles}
                onOpenAnchor={onOpenAnchor}
                onRetry={() => {
                  ask(turn.question);
                }}
              />
            ))}
          </ul>
        )}
      </div>

      <form
        className={cn("shrink-0 border-t border-border bg-surface", compact ? "px-3 py-2" : "px-6 py-3")}
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <div className={cn("mx-auto flex items-end gap-2", compact ? "" : "max-w-[780px]")}>
          <textarea
            value={draft}
            data-testid="qa-input"
            onChange={(event) => {
              setDraft(event.target.value);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                submit();
              }
            }}
            rows={compact ? 2 : 2}
            placeholder={compact ? "就这篇文献提问…" : "问点什么，例如：训练用了多少块什么型号的 GPU？"}
            aria-label="提问"
            className="min-h-[38px] flex-1 resize-none rounded-control border border-border bg-surface-2 px-3 py-2 text-[var(--text-base)] text-ink outline-none placeholder:text-ink-2"
          />
          {streaming ? (
            <Button
              type="button"
              variant="secondary"
              size="icon"
              aria-label="停止生成"
              onClick={stop}
            >
              <Square className="size-4" aria-hidden />
            </Button>
          ) : (
            <Button
              type="submit"
              variant="primary"
              size="icon"
              aria-label="发送"
              disabled={!draft.trim() || Boolean(blocked)}
            >
              <ArrowUp className="size-4" aria-hidden />
            </Button>
          )}
        </div>
        <p
          className={cn(
            "mx-auto mt-1.5 text-[var(--text-xs)]",
            compact ? "" : "max-w-[780px]",
            blocked ? "text-warn-text" : "text-ink-2",
          )}
        >
          {blocked ?? "回答逐句回验原文；找不到依据的数字与名词会被删除，而不是被改写。"}
        </p>
      </form>
    </div>
  );
}

function EmptyPrompt({ compact, onPreset }: { compact: boolean; onPreset: (preset: string) => void }) {
  return (
    <div className={cn("mx-auto text-center", compact ? "pt-6" : "max-w-[720px] pt-10")}>
      <MessageSquareQuote className="mx-auto size-8 text-ink-2" strokeWidth={1.5} aria-hidden />
      <p className="mt-3 text-[var(--text-md)] font-medium text-ink">
        {compact ? "就这篇文献提问" : "就你的文献提问"}
      </p>
      <p className="mt-1 text-[var(--text-sm)] text-ink-2">
        每条结论都会附原文锚点，点开即可定位到 PDF 中的对应位置。
      </p>
      <div className="mt-5 flex flex-wrap justify-center gap-2">
        {PRESETS.slice(0, compact ? 2 : PRESETS.length).map((preset) => (
          <button
            key={preset}
            type="button"
            onClick={() => {
              onPreset(preset);
            }}
            className="rounded-full border border-border bg-surface px-3 py-1.5 text-[var(--text-sm)] text-ink-2 transition-colors duration-[--dur-fast] hover:border-primary hover:text-primary"
          >
            {preset}
          </button>
        ))}
      </div>
    </div>
  );
}

interface TurnViewProps {
  turn: QaTurn;
  docTitles: Record<string, string>;
  onOpenAnchor: (anchor: QaAnchor) => void;
  onRetry: () => void;
}

function TurnView({ turn, docTitles, onOpenAnchor, onRetry }: TurnViewProps) {
  const documents = { ...docTitles, ...(turn.documents ?? {}) };
  return (
    <li data-testid="qa-turn" data-qa-status={turn.status} className="space-y-2.5">
      <p className="ml-auto w-fit max-w-[85%] rounded-card bg-primary px-4 py-2 text-[var(--text-base)] text-white">
        {turn.question}
      </p>

      {turn.table ? (
        <CompareAnswer table={turn.table} documents={documents} onOpenAnchor={onOpenAnchor} />
      ) : turn.refused ? (
        <RefusalCard flags={turn.flags} />
      ) : (
        <div className="rounded-card border border-border bg-surface p-4">
          {turn.answer ? (
            <AnswerText
              answer={turn.answer}
              citations={turn.citations}
              documents={documents}
              onOpenAnchor={onOpenAnchor}
            />
          ) : (
            <Skeleton className="h-4 w-48" />
          )}
          {turn.status === "streaming" && (
            <span className="ml-0.5 inline-block h-4 w-[3px] animate-pulse rounded bg-primary align-middle" aria-hidden />
          )}
        </div>
      )}

      {turn.status === "error" && <ErrorCard message={turn.error ?? "问答失败"} onRetry={onRetry} />}
      {turn.flags.length > 0 && !turn.refused && !turn.table && <FlagList flags={turn.flags} />}
    </li>
  );
}

function AnswerText({
  answer,
  citations,
  documents,
  onOpenAnchor,
}: {
  answer: string;
  citations: QaCitation[];
  documents: Record<string, string>;
  onOpenAnchor: (anchor: QaAnchor) => void;
}) {
  const byMarker = new Map(citations.map((citation) => [citation.marker, citation]));
  const parts = answer.split(/(\[\d+\])/g);
  return (
    <p className="text-[var(--text-base)] leading-relaxed text-ink">
      {parts.map((part, index) => {
        const citation = byMarker.get(part);
        if (!citation) return <Fragment key={index}>{part}</Fragment>;
        return (
          <AnchorChip
            key={index}
            anchor={citation.anchor}
            marker={part}
            quote={citation.quote}
            docTitle={documents[citation.anchor.doc_id] ?? citation.anchor.doc_id}
            onOpen={onOpenAnchor}
            className="mx-0.5"
          />
        );
      })}
    </p>
  );
}

function RefusalCard({ flags }: { flags: QaFlag[] }) {
  const reason = flags.find((flag) => flag.kind === "weak_support")?.text;
  return (
    <div
      className="rounded-card border border-border bg-surface-2 p-4"
      data-testid="qa-refusal"
    >
      <p className="flex items-center gap-2 text-[var(--text-base)] font-medium text-ink">
        <ShieldAlert className="size-4 text-warn-text" aria-hidden />
        未在所选文献中找到依据
      </p>
      <p className="mt-1 text-[var(--text-sm)] text-ink-2">
        可以扩大检索范围，或换一种问法。系统不会在缺少原文依据时给出结论。
      </p>
      {reason && <p className="mt-2 text-[var(--text-xs)] text-ink-2">原因：{reason}</p>}
    </div>
  );
}

function ErrorCard({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="rounded-card border border-danger/40 bg-surface p-3" data-testid="qa-error">
      <p className="text-[var(--text-sm)] font-medium text-danger-text">回答失败</p>
      <p className="mt-1 text-[var(--text-sm)] text-ink-2">{message}</p>
      <Button variant="secondary" size="sm" className="mt-2" onClick={onRetry}>
        重试
      </Button>
    </div>
  );
}

function FlagList({ flags }: { flags: QaFlag[] }) {
  return (
    <details className="rounded-control border border-border bg-surface-2 px-3 py-2">
      <summary className="flex cursor-pointer items-center gap-1.5 text-[var(--text-xs)] text-ink-2">
        <AlertTriangle className="size-3.5 text-warn-text" aria-hidden />
        校验提示（{flags.length}）
      </summary>
      <ul className="mt-2 space-y-1 text-[var(--text-xs)] text-ink-2">
        {flags.map((flag, index) => (
          <li key={`${flag.kind}-${index}`}>{flag.text}</li>
        ))}
      </ul>
    </details>
  );
}
