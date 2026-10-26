import { AlertTriangle, Inbox, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "./Button";
import { cn } from "@/lib/cn";

/** Every async region needs all three states (02 §2). */

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn("animate-pulse rounded-control bg-surface-2", className)}
      role="status"
      aria-label="加载中"
    />
  );
}

export function EmptyState({
  title,
  description,
  action,
  icon,
}: {
  title: string;
  description: string;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
      <div className="flex size-12 items-center justify-center rounded-card bg-surface-2 text-ink-2">
        {icon ?? <Inbox className="size-6" aria-hidden />}
      </div>
      <div className="space-y-1">
        <p className="text-[var(--text-md)] font-medium text-ink">{title}</p>
        <p className="max-w-[42ch] text-[var(--text-sm)] text-ink-2">{description}</p>
      </div>
      {action}
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
  detail,
}: {
  message: string;
  onRetry?: () => void;
  detail?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
      <div className="flex size-12 items-center justify-center rounded-card bg-surface-2 text-danger-text">
        <AlertTriangle className="size-6" aria-hidden />
      </div>
      <div className="space-y-1">
        <p className="text-[var(--text-md)] font-medium text-ink">{message}</p>
        {detail && <p className="max-w-[42ch] text-[var(--text-sm)] text-ink-2">{detail}</p>}
      </div>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          <RefreshCw className="size-4" aria-hidden />
          重试
        </Button>
      )}
    </div>
  );
}
