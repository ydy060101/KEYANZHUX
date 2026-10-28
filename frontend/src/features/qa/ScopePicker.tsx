import { Check, ChevronDown, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/design/Button";
import type { Document } from "@/features/library/api";
import { cn } from "@/lib/cn";
import type { QaScope, QaScopeType } from "./api";

const SCOPES: { key: QaScopeType; label: string }[] = [
  { key: "doc", label: "单篇" },
  { key: "set", label: "选集" },
  { key: "all", label: "全库" },
];

export interface ScopePickerProps {
  scope: QaScope;
  onChange: (scope: QaScope) => void;
  documents: Document[];
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  /** Compare mode accepts at most five columns; QA has no such limit. */
  max?: number;
}

/**
 * The scope selector (02 §4.3): one paper, a checked set, or the whole
 * library. The set picker is a real multi-select over parsed documents; no
 * placeholder rows are offered for files the backend cannot answer from.
 */
export function ScopePicker({
  scope,
  onChange,
  documents,
  loading,
  error,
  onRetry,
  max,
}: ScopePickerProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const selected = useMemo(() => new Set(scope.doc_ids), [scope.doc_ids]);
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return needle ? documents.filter((doc) => doc.title.toLowerCase().includes(needle)) : documents;
  }, [documents, query]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const choose = (type: QaScopeType) => {
    setOpen(false);
    if (type === "all") onChange({ type, doc_ids: [] });
    else if (type === "doc") onChange({ type, doc_ids: scope.doc_ids.slice(0, 1) });
    else onChange({ type, doc_ids: scope.doc_ids });
  };

  const toggle = (id: string) => {
    if (selected.has(id)) {
      onChange({ ...scope, doc_ids: scope.doc_ids.filter((item) => item !== id) });
      return;
    }
    if (max !== undefined && scope.doc_ids.length >= max) return;
    onChange({ ...scope, doc_ids: [...scope.doc_ids, id] });
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex rounded-control border border-border p-0.5" role="group" aria-label="检索范围">
        {SCOPES.map((item) => (
          <button
            key={item.key}
            type="button"
            aria-pressed={scope.type === item.key}
            onClick={() => {
              choose(item.key);
            }}
            className={cn(
              "rounded-[6px] px-3 py-1 text-[var(--text-sm)] transition-colors duration-[--dur-fast]",
              scope.type === item.key
                ? "bg-surface-2 font-medium text-ink"
                : "text-ink-2 hover:text-ink",
            )}
          >
            {item.label}
          </button>
        ))}
      </div>

      {scope.type === "doc" && (
        <div className="relative inline-flex items-center">
          <select
            aria-label="选择文献"
            value={scope.doc_ids[0] ?? ""}
            disabled={loading || documents.length === 0}
            onChange={(event) => {
              onChange({ type: "doc", doc_ids: [event.target.value] });
            }}
            className="h-8 max-w-[260px] appearance-none truncate rounded-control border border-border bg-surface pl-3 pr-8 text-[var(--text-sm)] text-ink outline-none disabled:opacity-60"
          >
            <option value="" disabled>
              {loading ? "加载文献…" : documents.length === 0 ? "没有已解析文献" : "选择文献"}
            </option>
            {documents.map((doc) => (
              <option key={doc.id} value={doc.id}>
                {doc.title}
              </option>
            ))}
          </select>
          <ChevronDown
            className="pointer-events-none absolute right-2 size-3.5 text-ink-2"
            aria-hidden
          />
        </div>
      )}

      {scope.type === "set" && (
        <div className="relative">
          <button
            type="button"
            aria-expanded={open}
            aria-haspopup="listbox"
            onClick={() => {
              setOpen((value) => !value);
            }}
            className="flex h-8 max-w-[280px] items-center gap-1.5 rounded-control border border-border bg-surface px-3 text-[var(--text-sm)] text-ink hover:bg-surface-2"
          >
            <span className="truncate">
              {scope.doc_ids.length === 0 ? "选择文献" : `已选 ${scope.doc_ids.length} 篇`}
            </span>
            <ChevronDown className="size-3.5 text-ink-2" aria-hidden />
          </button>
          {open && (
            <>
              <button
                type="button"
                aria-label="关闭文献选择"
                tabIndex={-1}
                className="fixed inset-0 z-10 cursor-default"
                onClick={() => {
                  setOpen(false);
                }}
              />
              <div className="absolute left-0 top-full z-20 mt-1 w-[320px] rounded-card border border-border bg-surface p-2 shadow-lg">
                <div className="relative">
                  <Search
                    className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-ink-2"
                    aria-hidden
                  />
                  <input
                    value={query}
                    onChange={(event) => {
                      setQuery(event.target.value);
                    }}
                    aria-label="搜索文献"
                    placeholder="搜索标题…"
                    className="h-8 w-full rounded-control border border-border bg-surface-2 pl-8 pr-2 text-[var(--text-sm)] text-ink outline-none placeholder:text-ink-2"
                  />
                </div>
                <ul className="mt-2 max-h-[260px] overflow-y-auto" role="listbox" aria-label="文献列表">
                  {filtered.length === 0 && (
                    <li className="px-2 py-4 text-center text-[var(--text-sm)] text-ink-2">
                      没有匹配的文献
                    </li>
                  )}
                  {filtered.map((doc) => {
                    const checked = selected.has(doc.id);
                    const full = max !== undefined && !checked && scope.doc_ids.length >= max;
                    return (
                      <li key={doc.id} role="option" aria-selected={checked}>
                        <button
                          type="button"
                          disabled={full}
                          onClick={() => {
                            toggle(doc.id);
                          }}
                          className={cn(
                            "flex w-full items-center gap-2 rounded-control px-2 py-1.5 text-left",
                            "text-[var(--text-sm)] text-ink hover:bg-surface-2 disabled:opacity-40",
                          )}
                        >
                          <span
                            className={cn(
                              "flex size-4 shrink-0 items-center justify-center rounded border",
                              checked ? "border-primary bg-primary text-white" : "border-border",
                            )}
                            aria-hidden
                          >
                            {checked && <Check className="size-3" strokeWidth={3} />}
                          </span>
                          <span className="truncate" title={doc.title}>
                            {doc.title}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
                <div className="mt-1 flex items-center justify-between border-t border-border px-1 pt-2">
                  <span className="text-[var(--text-xs)] text-ink-2">
                    {max !== undefined ? `对比最多 ${max} 篇` : "可多选"}
                  </span>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => {
                      setOpen(false);
                    }}
                  >
                    完成
                  </Button>
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {error && (
        <span className="flex items-center gap-2 text-[var(--text-xs)] text-danger-text">
          {error}
          <button type="button" onClick={onRetry} className="underline underline-offset-2">
            重试
          </button>
        </span>
      )}
    </div>
  );
}
