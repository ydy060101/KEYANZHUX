import { CheckCircle2, CircleAlert, Loader2, X } from "lucide-react";

import { useJobs } from "@/app/jobs";
import { cn } from "@/lib/cn";

const STATUS_LABEL = {
  queued: "排队中",
  running: "进行中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
} as const;

export function JobCenter() {
  const jobs = useJobs((s) => s.jobs);
  const remove = useJobs((s) => s.remove);
  const clearFinished = useJobs((s) => s.clearFinished);

  if (jobs.length === 0) {
    return <p className="px-4 py-8 text-center text-[var(--text-sm)] text-ink-2">暂无任务</p>;
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-border px-4 py-2">
        <span className="text-[var(--text-sm)] text-ink-2">{jobs.length} 个任务</span>
        <button
          type="button"
          onClick={() => {
            clearFinished();
          }}
          className="text-[var(--text-sm)] text-ink-2 hover:text-ink"
        >
          清除已完成
        </button>
      </div>
      <ul className="flex-1 overflow-y-auto p-2">
        {jobs.map((job) => (
          <li key={job.id} className="rounded-control px-2 py-2 hover:bg-surface-2">
            <div className="flex items-start gap-2">
              <span className="mt-0.5 shrink-0">
                {job.status === "succeeded" && <CheckCircle2 className="size-4 text-success-text" aria-hidden />}
                {job.status === "failed" && <CircleAlert className="size-4 text-danger-text" aria-hidden />}
                {(job.status === "running" || job.status === "queued") && (
                  <Loader2 className="size-4 animate-spin text-primary" aria-hidden />
                )}
                {job.status === "cancelled" && <X className="size-4 text-ink-2" aria-hidden />}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-[var(--text-sm)] text-ink">{job.label}</p>
                <p className="text-[var(--text-xs)] text-ink-2">
                  {STATUS_LABEL[job.status]} · {job.stage}
                </p>
                {job.status === "running" && (
                  <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-surface-2">
                    <div
                      className={cn("h-full rounded-full bg-primary transition-[width] duration-[--dur-base]")}
                      style={{ width: `${Math.round(job.progress * 100)}%` }}
                    />
                  </div>
                )}
                {job.error && <p className="mt-1 text-[var(--text-xs)] text-danger-text">{job.error}</p>}
              </div>
              <button
                type="button"
                aria-label={`移除任务 ${job.label}`}
                onClick={() => {
                  remove(job.id);
                }}
                className="shrink-0 rounded p-1 text-ink-2 hover:text-ink"
              >
                <X className="size-3.5" aria-hidden />
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
