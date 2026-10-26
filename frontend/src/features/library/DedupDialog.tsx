import { ArrowRightLeft, Check, CopyCheck, FileWarning } from "lucide-react";
import { useState } from "react";

import { Button } from "@/design/Button";
import { useVersionDiff } from "./api";
import type { DedupInfo } from "./api";

const LEVEL_LABEL: Record<DedupInfo["level"], string> = {
  exact_duplicate: "完全相同的文件",
  same_paper_other_version: "同一篇论文的另一个版本",
  content_duplicate: "内容重复",
  possible_duplicate: "可能重复",
};

const SUGGESTION_HINT: Record<DedupInfo["suggestion"], string> = {
  keep_existing: "建议保留库中已有版本",
  replace: "建议用新上传的版本替换",
  ask: "需要你确认保留哪一个",
};

export interface DedupPrompt {
  info: DedupInfo;
  docId: string;
  filename: string;
}

export function DedupDialog({
  prompt,
  pending,
  onResolve,
  onDismiss,
}: {
  prompt: DedupPrompt;
  pending: boolean;
  onResolve: (action: "keep_existing" | "replace" | "keep_both") => void;
  onDismiss: () => void;
}) {
  const [showDiff, setShowDiff] = useState(false);
  const { info, docId } = prompt;
  const diff = useVersionDiff(showDiff ? docId : null, showDiff ? info.matched_doc_id : null);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true" aria-labelledby="dedup-title">
      <div className="w-full max-w-[560px] rounded-dialog border border-border bg-surface shadow-xl">
        <div className="flex items-start gap-3 border-b border-border px-5 py-4">
          <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-card bg-warn/10 text-warn-text">
            <FileWarning className="size-5" aria-hidden />
          </span>
          <div className="min-w-0 flex-1">
            <h2 id="dedup-title" className="text-[var(--text-md)] font-medium text-ink">
              检测到重复文献
            </h2>
            <p className="mt-0.5 text-[var(--text-sm)] text-ink-2">
              {LEVEL_LABEL[info.level]} · 相似度 {Math.round(info.similarity * 100)}%
            </p>
          </div>
        </div>

        <div className="space-y-3 px-5 py-4">
          <p className="text-[var(--text-sm)] text-ink">{info.reason}</p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-[var(--text-sm)]">
            <dt className="text-ink-2">库中版本</dt>
            <dd className="text-ink">{info.existing_version ?? "未标注版本"}</dd>
            <dt className="text-ink-2">新上传</dt>
            <dd className="text-ink">{info.new_version ?? prompt.filename}</dd>
          </dl>
          <p className="rounded-control bg-surface-2 px-3 py-2 text-[var(--text-sm)] text-ink-2">
            {SUGGESTION_HINT[info.suggestion]}
          </p>

          <div>
            <Button size="sm" variant="ghost" onClick={() => { setShowDiff((v) => !v); }}>
              <ArrowRightLeft className="size-4" aria-hidden />
              {showDiff ? "收起修订摘要" : "查看修订摘要"}
            </Button>
            {showDiff && (
              <div className="mt-2 rounded-control border border-border p-3">
                {diff.isPending && <p className="text-[var(--text-sm)] text-ink-2">正在对比…</p>}
                {diff.isError && (
                  <p className="text-[var(--text-sm)] text-danger-text">
                    无法生成修订摘要：{diff.error instanceof Error ? diff.error.message : "请稍后重试"}
                  </p>
                )}
                {diff.data && (
                  <div className="space-y-2">
                    <p className="text-[var(--text-sm)] text-ink">{diff.data.summary}</p>
                    {diff.data.comparable !== false && (
                      <ul className="grid grid-cols-2 gap-x-4 gap-y-1 text-[var(--text-xs)] text-ink-2">
                        <li>新增章节 {diff.data.stats.sections_added ?? 0}</li>
                        <li>删除章节 {diff.data.stats.sections_removed ?? 0}</li>
                        <li>修改章节 {diff.data.stats.sections_modified ?? 0}</li>
                        <li>参考文献 +{diff.data.stats.references_added ?? 0} / -{diff.data.stats.references_removed ?? 0}</li>
                      </ul>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        <div className="flex flex-wrap justify-end gap-2 border-t border-border px-5 py-3">
          <Button variant="ghost" disabled={pending} onClick={onDismiss}>
            稍后处理
          </Button>
          <Button variant="secondary" disabled={pending} onClick={() => { onResolve("keep_both"); }}>
            <CopyCheck className="size-4" aria-hidden />
            两者都保留
          </Button>
          <Button variant="secondary" disabled={pending} onClick={() => { onResolve("replace"); }}>
            <ArrowRightLeft className="size-4" aria-hidden />
            覆盖
          </Button>
          <Button variant="primary" loading={pending} onClick={() => { onResolve("keep_existing"); }}>
            <Check className="size-4" aria-hidden />
            保留现有
          </Button>
        </div>
      </div>
    </div>
  );
}
