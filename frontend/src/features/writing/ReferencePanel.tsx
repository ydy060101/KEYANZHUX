import { AlertTriangle, CheckCircle2, CircleAlert, Download, ExternalLink, Loader2, SearchCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/design/Button";
import { EmptyState } from "@/design/States";
import { cn } from "@/lib/cn";
import {
  downloadText,
  fetchBibtex,
  verifyTitles,
  type OutlineFlag,
  type ReferenceCheck,
  type WritingReference,
} from "./api";

export interface ReferencePanelProps {
  references: WritingReference[];
  flags: OutlineFlag[];
  usedKeys: string[];
  selectedKey: string | null;
  draftId: string | null;
  onSelect: (key: string | null) => void;
}

function linkFor(reference: WritingReference): string | null {
  if (reference.sourceUrl) return reference.sourceUrl;
  if (reference.doi) return `https://doi.org/${reference.doi}`;
  if (reference.arxivId) return `https://arxiv.org/abs/${reference.arxivId}`;
  return null;
}

function ReferenceCard({
  reference,
  used,
  selected,
  onSelect,
  register,
}: {
  reference: WritingReference;
  used: boolean;
  selected: boolean;
  onSelect: () => void;
  register: (node: HTMLLIElement | null) => void;
}) {
  const href = linkFor(reference);
  return (
    <li
      ref={register}
      data-testid="writing-reference"
      data-reference-key={reference.key}
      className={cn(
        "rounded-control border p-2.5 transition-colors duration-[--dur-fast]",
        selected ? "border-primary bg-primary/5" : "border-border bg-surface",
      )}
    >
      <div className="flex items-start gap-2">
        {reference.status === "verified" ? (
          <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success-text" aria-hidden />
        ) : (
          <CircleAlert className="mt-0.5 size-4 shrink-0 text-warn-text" aria-hidden />
        )}
        <button
          type="button"
          onClick={onSelect}
          className="min-w-0 flex-1 text-left text-[var(--text-sm)] font-medium leading-snug text-ink hover:text-primary"
        >
          {reference.title}
        </button>
      </div>
      <p className="mt-1 pl-6 text-[var(--text-xs)] text-ink-2">
        {reference.authors.length > 0 ? `${reference.authors.slice(0, 3).join(", ")}${reference.authors.length > 3 ? " 等" : ""}` : "作者未找到"}
        {reference.year !== null ? ` · ${reference.year}` : ""}
      </p>
      <div className="mt-1.5 flex flex-wrap items-center gap-2 pl-6 text-[var(--text-xs)]">
        <span className={cn("rounded px-1.5 py-0.5", used ? "bg-primary/10 text-primary" : "bg-surface-2 text-ink-2")}>
          {used ? "已引用" : "未引用"}
        </span>
        <span className={reference.status === "verified" ? "text-success-text" : "text-warn-text"}>
          {reference.status === "verified" ? "已验证" : "未验证"}
        </span>
        {href && (
          <a
            href={href}
            target="_blank"
            rel="noreferrer"
            className="ml-auto inline-flex items-center gap-1 text-primary hover:underline"
          >
            打开来源
            <ExternalLink className="size-3" aria-hidden />
          </a>
        )}
      </div>
      {reference.key && (
        <p className="mt-1 truncate pl-6 font-mono text-[11px] text-ink-2" title={reference.key}>
          {reference.key}
        </p>
      )}
    </li>
  );
}

export function ReferencePanel({ references, flags, usedKeys, selectedKey, draftId, onSelect }: ReferencePanelProps) {
  const [title, setTitle] = useState("");
  const [checks, setChecks] = useState<ReferenceCheck[]>([]);
  const [verifying, setVerifying] = useState(false);
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const [bibtexBusy, setBibtexBusy] = useState(false);
  const [bibtexError, setBibtexError] = useState<string | null>(null);
  const [bibtexDone, setBibtexDone] = useState(false);
  const cards = useRef(new Map<string, HTMLLIElement>());

  useEffect(() => {
    if (!selectedKey) return;
    cards.current.get(selectedKey)?.scrollIntoView({ block: "nearest" });
  }, [selectedKey]);

  const missing = usedKeys.filter((key) => !references.some((reference) => reference.key === key));

  const verify = async () => {
    const value = title.trim();
    if (!value) return;
    setVerifying(true);
    setVerifyError(null);
    try {
      const result = await verifyTitles([value]);
      setChecks((current) => [...result.filter((item) => !current.some((old) => old.title === item.title)), ...current]);
      setTitle("");
    } catch (reason) {
      setVerifyError(reason instanceof Error ? reason.message : "校验失败");
    } finally {
      setVerifying(false);
    }
  };

  const exportBibtex = async () => {
    if (!draftId) return;
    setBibtexBusy(true);
    setBibtexError(null);
    setBibtexDone(false);
    try {
      const body = await fetchBibtex(draftId);
      if (!body.trim()) throw new Error("草稿中没有可导出的已验证文献");
      downloadText(`${draftId.slice(0, 8)}.bib`, body, "application/x-bibtex;charset=utf-8");
      setBibtexDone(true);
    } catch (reason) {
      setBibtexError(reason instanceof Error ? reason.message : "导出失败");
    } finally {
      setBibtexBusy(false);
    }
  };

  return (
    <aside className="flex w-[300px] shrink-0 flex-col border-l border-border bg-surface" data-testid="writing-references">
      <div className="flex items-center justify-between border-b border-border px-3 py-2.5">
        <h2 className="text-[var(--text-sm)] font-medium text-ink">参考文献校验</h2>
        <span className="text-[var(--text-xs)] text-ink-2">
          {references.length} 篇 · 已引用 {usedKeys.length}
        </span>
      </div>

      <div className="app-scroll min-h-0 flex-1 space-y-3 p-3">
        {flags.length > 0 && (
          <ul className="space-y-1.5" aria-label="框架提示">
            {flags.map((flag, index) => (
              <li
                key={`${flag.kind}-${index}`}
                data-testid="writing-flag"
                className="flex items-start gap-1.5 rounded-control bg-warn/10 p-2 text-[var(--text-xs)] leading-relaxed text-warn-text"
              >
                <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                {flag.text}
              </li>
            ))}
          </ul>
        )}

        {references.length === 0 && missing.length === 0 ? (
          <EmptyState
            title="还没有参考文献"
            description="生成框架后会检索并核验真实文献；核验不通过的候选不会出现在这里。"
            icon={<SearchCheck className="size-6" aria-hidden />}
          />
        ) : (
          <ul className="space-y-2">
            {references.map((reference) => (
              <ReferenceCard
                key={`${reference.key}-${reference.title}`}
                reference={reference}
                used={usedKeys.includes(reference.key)}
                selected={selectedKey === reference.key}
                onSelect={() => {
                  onSelect(reference.key);
                }}
                register={(node) => {
                  if (node) cards.current.set(reference.key, node);
                  else cards.current.delete(reference.key);
                }}
              />
            ))}
            {missing.map((key) => (
              <li
                key={`missing-${key}`}
                data-testid="writing-reference-missing"
                className={cn(
                  "flex items-start gap-2 rounded-control border p-2.5",
                  selectedKey === key ? "border-warn bg-warn/10" : "border-border bg-surface",
                )}
              >
                <CircleAlert className="mt-0.5 size-4 shrink-0 text-warn-text" aria-hidden />
                <div className="min-w-0">
                  <p className="text-[var(--text-sm)] font-medium text-ink">[待补充]</p>
                  <p className="mt-0.5 break-all font-mono text-[11px] text-ink-2">引用键 {key} 未匹配到已验证文献</p>
                </div>
              </li>
            ))}
          </ul>
        )}

        <section className="rounded-control border border-border p-2.5">
          <h3 className="text-[var(--text-xs)] font-medium text-ink">手动核验一个标题</h3>
          <p className="mt-0.5 text-[11px] leading-relaxed text-ink-2">
            只显示 Crossref/OpenAlex/arXiv 的真实记录；结果不写入草稿。
          </p>
          <div className="mt-2 flex gap-1.5">
            <input
              value={title}
              onChange={(event) => {
                setTitle(event.target.value);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") void verify();
              }}
              placeholder="输入论文标题"
              aria-label="待核验的论文标题"
              data-testid="writing-verify-input"
              className="h-8 min-w-0 flex-1 rounded-control border border-border bg-surface-2 px-2 text-[var(--text-xs)] text-ink outline-none placeholder:text-ink-2 focus:border-primary"
            />
            <Button
              size="sm"
              variant="secondary"
              data-testid="writing-verify-button"
              loading={verifying}
              disabled={!title.trim()}
              onClick={() => {
                void verify();
              }}
            >
              核验
            </Button>
          </div>
          {verifyError && <p className="mt-1.5 text-[11px] text-danger-text">{verifyError}</p>}
          {checks.length > 0 && (
            <ul className="mt-2 space-y-1.5">
              {checks.map((check) => (
                <li key={`${check.title}-${check.status}`} className="flex items-start gap-1.5 text-[11px] leading-relaxed">
                  {check.status === "verified" ? (
                    <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-success-text" aria-hidden />
                  ) : (
                    <CircleAlert className="mt-0.5 size-3.5 shrink-0 text-warn-text" aria-hidden />
                  )}
                  <span className="min-w-0 flex-1">
                    <span className="line-clamp-2 text-ink">{check.title}</span>
                    <span className={check.status === "verified" ? "ml-1 text-success-text" : "ml-1 text-warn-text"}>
                      {check.status === "verified" ? "已验证" : "未验证"}
                    </span>
                    {check.sourceUrl && (
                      <a href={check.sourceUrl} target="_blank" rel="noreferrer" className="ml-1 text-primary hover:underline">
                        来源
                      </a>
                    )}
                    {!check.sourceUrl && check.doi && (
                      <a
                        href={`https://doi.org/${check.doi}`}
                        target="_blank"
                        rel="noreferrer"
                        className="ml-1 text-primary hover:underline"
                      >
                        DOI
                      </a>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <div className="border-t border-border p-3">
        {bibtexError && <p className="mb-1.5 text-[11px] text-danger-text">{bibtexError}</p>}
        {bibtexDone && <p className="mb-1.5 text-[11px] text-success-text">BibTeX 已下载（仅含已验证条目）。</p>}
        <Button
          size="sm"
          variant="secondary"
          className="w-full"
          data-testid="writing-bibtex"
          disabled={!draftId}
          loading={bibtexBusy}
          onClick={() => {
            void exportBibtex();
          }}
        >
          {bibtexBusy ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <Download className="size-3.5" aria-hidden />}
          导出 BibTeX
        </Button>
      </div>
    </aside>
  );
}
