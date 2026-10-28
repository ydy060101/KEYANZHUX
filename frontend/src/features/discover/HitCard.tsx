import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, ExternalLink, FileDown } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Button } from "@/design/Button";
import { importPaper, sourceLabel } from "@/features/discover/api";
import { useJobStream } from "@/features/library/jobs";

export interface HitCardProps {
  title: string;
  source: string;
  extId: string;
  authors: string[];
  year: number | null;
  abstract: string | null;
  pdfUrl: string | null;
  score?: number;
  reasons?: string[];
  inLibrary?: boolean;
}

function resultDocId(result: unknown): string | null {
  if (typeof result !== "object" || result === null) return null;
  const value = (result as Record<string, unknown>).doc_id;
  return typeof value === "string" ? value : null;
}

/**
 * One search hit or recommendation (T5.1/T5.6).
 *
 * Importing creates a job; the card follows it over SSE and links to the
 * reader once the parse that the import queued has a document. The score and
 * reasons come from the backend and are shown verbatim — the UI never invents
 * a justification for a paper it was handed.
 */
export function HitCard({
  title,
  source,
  extId,
  authors,
  year,
  abstract,
  pdfUrl,
  score,
  reasons = [],
  inLibrary = false,
}: HitCardProps) {
  const [jobId, setJobId] = useState<string | null>(null);
  const [done, setDone] = useState(inLibrary);
  const importMutation = useMutation({
    mutationFn: () => importPaper(source, extId),
    onSuccess: (job) => {
      setJobId(job.id);
    },
  });
  const job = useJobStream(jobId, "导入文献");
  const docId = resultDocId(job.data?.result);
  const running = jobId !== null && job.data?.status !== "succeeded" && job.data?.status !== "failed";
  const failed = job.data?.status === "failed" || importMutation.isError;
  const message = importMutation.error instanceof Error
    ? importMutation.error.message
    : failed
      ? (job.data?.error ?? "导入失败")
      : null;

  return (
    <article
      data-testid="discover-hit"
      className="flex h-full flex-col gap-2 rounded-card border border-border bg-surface p-4"
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-[var(--text-base)] font-medium leading-snug text-ink">{title}</h3>
        {typeof score === "number" && (
          <span
            className="shrink-0 rounded-full bg-surface-2 px-2 py-0.5 text-[var(--text-xs)] tabular-nums text-ink-2"
            title="与库内文献标题的关键词重合度"
          >
            {score.toFixed(2)}
          </span>
        )}
      </div>
      <p className="text-[var(--text-sm)] text-ink-2">
        {authors.length > 0 ? `${authors.slice(0, 3).join(", ")}${authors.length > 3 ? " 等" : ""}` : "作者未提供"}
        {year ? ` · ${year}` : ""}
        {` · ${sourceLabel(source)}`}
      </p>
      {abstract && (
        <p className="line-clamp-3 text-[var(--text-sm)] leading-relaxed text-ink-2">{abstract}</p>
      )}
      {reasons.length > 0 && (
        <ul className="flex flex-wrap gap-1.5">
          {reasons.map((reason) => (
            <li
              key={reason}
              className="rounded-full bg-surface-2 px-2 py-0.5 text-[var(--text-xs)] text-ink-2"
            >
              {reason}
            </li>
          ))}
        </ul>
      )}
      <div className="mt-auto flex items-center gap-2 pt-2">
        {done || job.data?.status === "succeeded" ? (
          docId ? (
            <Link
              to={`/reader/${docId}`}
              className="flex items-center gap-1.5 text-[var(--text-sm)] font-medium text-primary hover:underline"
            >
              <CheckCircle2 className="size-4" aria-hidden />
              已入库，打开阅读
            </Link>
          ) : (
            <span className="flex items-center gap-1.5 text-[var(--text-sm)] text-success-text">
              <CheckCircle2 className="size-4" aria-hidden />
              已在库中
            </span>
          )
        ) : (
          <Button
            size="sm"
            variant="primary"
            data-testid="discover-import"
            loading={running || importMutation.isPending}
            disabled={inLibrary || !pdfUrl}
            title={pdfUrl ? undefined : "该来源没有可直接下载的 PDF"}
            onClick={() => {
              setDone(false);
              importMutation.mutate();
            }}
          >
            {running ? "下载解析中…" : pdfUrl ? (
              <>
                <FileDown className="size-3.5" aria-hidden />
                入库
              </>
            ) : (
              "无可下载 PDF"
            )}
          </Button>
        )}
        {pdfUrl && (
          <a
            href={pdfUrl}
            target="_blank"
            rel="noreferrer"
            className="ml-auto flex items-center gap-1 text-[var(--text-sm)] text-ink-2 hover:text-ink"
          >
            <ExternalLink className="size-3.5" aria-hidden />
            PDF
          </a>
        )}
      </div>
      {message && (
        <p data-testid="discover-import-status" className="text-[var(--text-sm)] text-danger-text">
          {message}
        </p>
      )}
    </article>
  );
}
