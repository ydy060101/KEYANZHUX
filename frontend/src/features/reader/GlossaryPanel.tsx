import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, BookMarked, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/design/Button";
import { Skeleton } from "@/design/States";
import { fetchGlossary, saveGlossary, type GlossaryEntry } from "./translateApi";

/**
 * The reader's terminology list (T4.4).
 *
 * Add and delete are both "replace the list" calls: the backend returns the
 * new version, which the panel shows. The version is part of every block's
 * cache key, so the notice says plainly that an existing translation only
 * changes after the next translation run.
 */
export function GlossaryPanel() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["glossary"], queryFn: fetchGlossary });
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: saveGlossary,
    onSuccess: (data) => {
      queryClient.setQueryData(["glossary"], data);
      setNotice(`术语表已保存为 v${data.version}；重新翻译后按新术语生成。`);
      setSource("");
      setTarget("");
      setFormError(null);
    },
  });

  const entries = query.data?.entries ?? [];
  const busy = mutation.isPending;

  function commit(next: GlossaryEntry[]) {
    setNotice(null);
    setFormError(null);
    mutation.mutate(next);
  }

  function add() {
    const nextSource = source.trim();
    const nextTarget = target.trim();
    if (!nextSource || !nextTarget) {
      setFormError("请填写原文术语和译文术语");
      return;
    }
    const next = entries.filter(
      (entry) => entry.source.toLocaleLowerCase() !== nextSource.toLocaleLowerCase(),
    );
    next.push({ source: nextSource, target: nextTarget });
    commit(next);
  }

  function remove(entry: GlossaryEntry) {
    commit(entries.filter((item) => item.source !== entry.source));
  }

  return (
    <section
      className="mt-4 rounded-card border border-border bg-surface p-3"
      data-testid="glossary-panel"
    >
      <div className="flex items-center gap-1.5">
        <BookMarked className="size-4 text-ink-2" aria-hidden />
        <p className="text-[var(--text-sm)] font-medium text-ink">术语表</p>
        <span
          className="ml-auto rounded-full bg-surface-2 px-2 py-0.5 text-[var(--text-2xs)] tabular-nums text-ink-2"
          data-testid="glossary-version"
        >
          v{query.data?.version ?? 0}
        </span>
      </div>
      <p className="mt-1 text-[var(--text-xs)] leading-relaxed text-ink-2">
        指定术语的固定译法；修改版本会使整篇译文缓存失效，重新翻译后生效。
      </p>

      {query.isPending ? (
        <div className="mt-2 space-y-1.5" data-testid="glossary-loading">
          <Skeleton className="h-6 w-full" />
          <Skeleton className="h-6 w-4/5" />
        </div>
      ) : query.isError ? (
        <div className="mt-2 rounded-control bg-surface-2 px-2 py-1.5" data-testid="glossary-error">
          <p className="text-[var(--text-xs)] text-danger-text">{query.error.message}</p>
          <button
            type="button"
            onClick={() => {
              void query.refetch();
            }}
            className="mt-1 flex items-center gap-1 text-[var(--text-xs)] text-ink-2 hover:text-ink"
          >
            <RefreshCw className="size-3" aria-hidden />
            重试
          </button>
        </div>
      ) : entries.length === 0 ? (
        <p className="mt-2 text-[var(--text-xs)] text-ink-2" data-testid="glossary-empty">
          尚未添加术语。
        </p>
      ) : (
        <ul
          className="app-scroll mt-2 max-h-40 space-y-0.5 overflow-y-auto"
          data-testid="glossary-list"
        >
          {entries.map((entry) => (
            <GlossaryRow key={entry.source} entry={entry} disabled={busy} onRemove={remove} />
          ))}
        </ul>
      )}

      {query.isSuccess && (
        <div className="mt-2 grid grid-cols-2 gap-1.5">
          <input
            aria-label="原文术语"
            data-testid="glossary-source"
            value={source}
            maxLength={80}
            placeholder="原文术语"
            onChange={(event) => {
              setSource(event.target.value);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter") add();
            }}
            className="h-8 min-w-0 rounded-control border border-border bg-surface-2 px-2 text-[var(--text-xs)] text-ink outline-none placeholder:text-ink-2 focus:border-primary"
          />
          <input
            aria-label="译文术语"
            data-testid="glossary-target"
            value={target}
            maxLength={120}
            placeholder="译文术语"
            onChange={(event) => {
              setTarget(event.target.value);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter") add();
            }}
            className="h-8 min-w-0 rounded-control border border-border bg-surface-2 px-2 text-[var(--text-xs)] text-ink outline-none placeholder:text-ink-2 focus:border-primary"
          />
          <Button
            size="sm"
            variant="secondary"
            className="col-span-2"
            disabled={busy}
            onClick={add}
            data-testid="glossary-add"
          >
            <Plus className="size-3.5" aria-hidden />
            {busy ? "保存中…" : "添加术语"}
          </Button>
        </div>
      )}

      {(formError || mutation.isError) && (
        <p className="mt-1.5 text-[var(--text-xs)] text-danger-text" role="alert">
          {formError ?? (mutation.error instanceof Error ? mutation.error.message : "保存失败")}
        </p>
      )}
      {notice && (
        <p className="mt-1.5 text-[var(--text-xs)] text-success-text" data-testid="glossary-notice">
          {notice}
        </p>
      )}
    </section>
  );
}

function GlossaryRow({
  entry,
  disabled,
  onRemove,
}: {
  entry: GlossaryEntry;
  disabled: boolean;
  onRemove: (entry: GlossaryEntry) => void;
}) {
  return (
    <li
      className="flex items-center gap-1.5 rounded px-1 py-1 hover:bg-surface-2"
      data-glossary-entry={entry.source}
    >
      <span className="min-w-0 flex-1 truncate text-[var(--text-xs)] text-ink" title={entry.source}>
        {entry.source}
      </span>
      <ArrowRight className="size-3 shrink-0 text-ink-2" aria-hidden />
      <span className="min-w-0 flex-1 truncate text-[var(--text-xs)] text-ink" title={entry.target}>
        {entry.target}
      </span>
      <button
        type="button"
        aria-label={`删除术语 ${entry.source}`}
        disabled={disabled}
        onClick={() => {
          onRemove(entry);
        }}
        className="rounded p-0.5 text-ink-2 hover:bg-surface hover:text-danger-text disabled:opacity-40"
      >
        <Trash2 className="size-3.5" aria-hidden />
      </button>
    </li>
  );
}
