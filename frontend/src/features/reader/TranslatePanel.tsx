import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, Copy, Download, FileText, Languages, Loader2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/design/Button";
import { ErrorState } from "@/design/States";
import { useJobStream } from "@/features/library/jobs";
import { cn } from "@/lib/cn";
import { GlossaryPanel } from "./GlossaryPanel";
import {
  downloadTranslation,
  fetchTranslation,
  startDocumentTranslation,
  translateSelection,
  type Direction,
  type SelectionDone,
} from "./translateApi";

export interface TranslateRequest {
  text: string;
  nonce: number;
}

export interface TranslatePanelProps {
  docId: string;
  /** A selection handed over by the reader's floating toolbar (T4.1). */
  request: TranslateRequest | null;
}

type Status = "idle" | "streaming" | "done" | "error";

const DIRECTION_LABEL: Record<Direction, string> = { en2zh: "英 → 中", zh2en: "中 → 英" };

/**
 * The reader's translation tab (02 §4.2, T4.1/T4.2).
 *
 * A selection streams its translation here — first characters in well under
 * two seconds — and the whole paper is a job whose progress is the same SSE
 * stream the library uses. Formulas and code are restored by the backend, so
 * the panel never post-processes the text it shows.
 */
export function TranslatePanel({ docId, request }: TranslatePanelProps) {
  const [direction, setDirection] = useState<Direction>("en2zh");
  const [status, setStatus] = useState<Status>("idle");
  const [streamText, setStreamText] = useState("");
  const [meta, setMeta] = useState<SelectionDone | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [retryNonce, setRetryNonce] = useState(0);
  const queryClient = useQueryClient();
  const abortRef = useRef<AbortController | null>(null);

  const translationQuery = useQuery({
    queryKey: ["translation", docId, direction],
    queryFn: () => fetchTranslation(docId, direction),
    enabled: Boolean(docId),
  });

  const job = useJobStream(jobId, "翻译全文");
  const jobStatus = job.data?.status ?? null;
  const jobRunning = jobStatus === "queued" || jobStatus === "running";

  const reload = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["translation", docId, direction] });
  }, [direction, docId, queryClient]);

  useEffect(() => {
    if (jobStatus === "succeeded") reload();
  }, [jobStatus, reload]);

  useEffect(() => {
    if (!request) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setStatus("streaming");
    setStreamText("");
    setMeta(null);
    setError(null);
    setCopied(false);
    void translateSelection(
      request.text,
      direction,
      (event) => {
        if (event.type === "token") {
          setStreamText((prev) => prev + event.text);
          return;
        }
        if (event.type === "done") {
          setStreamText(event.data.text);
          setMeta(event.data);
          setStatus("done");
          return;
        }
        setError(event.message);
        setStatus("error");
      },
      controller.signal,
    ).catch((reason: unknown) => {
      if (controller.signal.aborted) return;
      setError(reason instanceof Error ? reason.message : "翻译失败");
      setStatus("error");
    });
    return () => {
      controller.abort();
    };
  }, [request, direction, retryNonce]);

  const start = useCallback(() => {
    setStarting(true);
    setStartError(null);
    void startDocumentTranslation(docId, direction, "md")
      .then((result) => {
        setJobId(result.job_id);
      })
      .catch((reason: unknown) => {
        setStartError(reason instanceof Error ? reason.message : "无法开始翻译");
      })
      .finally(() => {
        setStarting(false);
      });
  }, [direction, docId]);

  const download = useCallback(
    (format: "md" | "html") => {
      void downloadTranslation(docId, direction, format).catch((reason: unknown) => {
        setStartError(reason instanceof Error ? reason.message : "下载失败");
      });
    },
    [direction, docId],
  );

  const blocks = translationQuery.data?.blocks.length ?? 0;

  return (
    <div className="app-scroll min-h-0 flex-1 px-4 py-4" data-testid="translate-panel">
      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-[var(--text-sm)] font-medium text-ink">
          <Languages className="size-4 text-ink-2" aria-hidden />
          翻译
        </p>
        <div className="flex rounded-control border border-border p-0.5" role="group" aria-label="翻译方向">
          {(Object.keys(DIRECTION_LABEL) as Direction[]).map((key) => (
            <button
              key={key}
              type="button"
              aria-pressed={direction === key}
              onClick={() => {
                setDirection(key);
              }}
              className={cn(
                "rounded-[6px] px-2 py-1 text-[var(--text-xs)] transition-colors duration-[--dur-fast]",
                direction === key ? "bg-primary text-white" : "text-ink-2 hover:text-ink",
              )}
            >
              {DIRECTION_LABEL[key]}
            </button>
          ))}
        </div>
      </div>

      {status === "idle" ? (
        <p className="mt-2 text-[var(--text-xs)] leading-relaxed text-ink-2">
          在正文中选中文字即可翻译；公式、代码与引用标记保持原样。
        </p>
      ) : (
        <SelectionCard
          status={status}
          text={streamText}
          meta={meta}
          error={error}
          source={request?.text ?? ""}
          copied={copied}
          onCopy={() => {
            void navigator.clipboard.writeText(streamText).then(() => {
              setCopied(true);
            });
          }}
          onRetry={() => {
            setRetryNonce((prev) => prev + 1);
          }}
        />
      )}

      <section className="mt-5 rounded-card border border-border bg-surface p-3" data-testid="doc-translation">
        <p className="flex items-center gap-1.5 text-[var(--text-sm)] font-medium text-ink">
          <FileText className="size-4 text-ink-2" aria-hidden />
          整篇翻译
        </p>
        <p className="mt-1 text-[var(--text-xs)] leading-relaxed text-ink-2">
          按原文块逐段翻译，公式与代码保持原样；译文按块缓存，重跑只翻译改动过的段落。
        </p>

        {jobRunning && (
          <div className="mt-3" data-testid="doc-translation-progress">
            <p className="flex items-center gap-1.5 text-[var(--text-xs)] text-ink-2">
              <Loader2 className="size-3.5 animate-spin" aria-hidden />
              {job.data?.stage ?? "翻译中"} · {Math.round((job.data?.progress ?? 0) * 100)}%
            </p>
            <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface-2">
              <div
                className="h-full rounded-full bg-primary transition-[width] duration-[--dur-slow]"
                style={{ width: `${Math.round((job.data?.progress ?? 0) * 100)}%` }}
              />
            </div>
          </div>
        )}

        {jobStatus === "failed" && (
          <p className="mt-2 flex items-center gap-1.5 text-[var(--text-xs)] text-danger-text">
            <AlertTriangle className="size-3.5" aria-hidden />
            {job.data?.error || "翻译任务失败"}
          </p>
        )}

        {jobStatus === "succeeded" && (
          <p className="mt-2 text-[var(--text-xs)] text-success-text">整篇翻译完成。</p>
        )}

        {startError && (
          <p className="mt-2 text-[var(--text-xs)] text-danger-text">{startError}</p>
        )}

        {blocks > 0 ? (
          <>
            <p className="mt-3 text-[var(--text-xs)] text-ink-2" data-testid="doc-translation-count">
              已有译文 {blocks} 段。
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <Button size="sm" variant="secondary" onClick={() => { download("md"); }}>
                <Download className="size-3.5" aria-hidden />
                Markdown
              </Button>
              <Button size="sm" variant="secondary" onClick={() => { download("html"); }}>
                <Download className="size-3.5" aria-hidden />
                HTML
              </Button>
              <Button size="sm" variant="ghost" disabled={starting || jobRunning} onClick={start}>
                重新翻译
                <ArrowRight className="size-3.5" aria-hidden />
              </Button>
            </div>
          </>
        ) : (
          <Button
            size="sm"
            variant="primary"
            className="mt-3"
            disabled={starting || jobRunning}
            onClick={start}
            data-testid="doc-translation-start"
          >
            {starting ? "正在创建任务…" : "开始翻译"}
          </Button>
        )}
      </section>

      <GlossaryPanel />

      {translationQuery.isError && (
        <div className="mt-4">
          <ErrorState
            message="无法读取译文"
            detail={translationQuery.error.message}
            onRetry={() => {
              void translationQuery.refetch();
            }}
          />
        </div>
      )}
    </div>
  );
}

interface SelectionCardProps {
  status: Status;
  text: string;
  meta: SelectionDone | null;
  error: string | null;
  source: string;
  copied: boolean;
  onCopy: () => void;
  onRetry: () => void;
}

function SelectionCard({ status, text, meta, error, source, copied, onCopy, onRetry }: SelectionCardProps) {
  return (
    <section
      className="mt-3 rounded-card border border-border bg-surface p-3"
      data-testid="selection-translation"
      data-translation-status={status}
    >
      <p className="line-clamp-3 border-l-2 border-border pl-2 text-[var(--text-xs)] leading-relaxed text-ink-2">
        {source}
      </p>
      {status === "error" ? (
        <div className="mt-2">
          <p className="text-[var(--text-xs)] text-danger-text">{error ?? "翻译失败"}</p>
          <Button size="sm" variant="secondary" className="mt-2" onClick={onRetry}>
            重试
          </Button>
        </div>
      ) : (
        <p className="mt-2 whitespace-pre-wrap text-[var(--text-sm)] leading-relaxed text-ink">
          {text}
          {status === "streaming" && (
            <span className="ml-0.5 inline-block h-3.5 w-[3px] animate-pulse rounded bg-primary align-middle" aria-hidden />
          )}
        </p>
      )}
      {status !== "error" && (
        <div className="mt-2 flex items-center gap-2 text-[var(--text-xs)] text-ink-2" data-testid="selection-status">
          {meta?.first_token_ms != null && <span>首字 {meta.first_token_ms} ms</span>}
          {meta?.placeholders ? <span>· {meta.placeholders} 处公式/代码已保护</span> : null}
          {meta?.repaired && <span className="text-warn-text">· 占位符已修正</span>}
          {status === "done" && text && (
            <button
              type="button"
              onClick={onCopy}
              className="ml-auto flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-surface-2"
            >
              <Copy className="size-3" aria-hidden />
              {copied ? "已复制" : "复制"}
            </button>
          )}
        </div>
      )}
    </section>
  );
}
