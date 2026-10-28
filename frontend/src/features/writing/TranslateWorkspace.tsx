import { Check, Clipboard, Languages, Loader2, RotateCcw } from "lucide-react";
import { useState } from "react";

import { Button } from "@/design/Button";
import { translateAcademic } from "./api";

const LIMIT = 20_000;

export function TranslateWorkspace() {
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("");
  const [cached, setCached] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const translate = async () => {
    const value = source.trim();
    if (!value) return;
    setBusy(true);
    setError(null);
    setCopied(false);
    try {
      const result = await translateAcademic(value);
      setTarget(result.text);
      setCached(result.cached);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "翻译失败");
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    if (!target) return;
    try {
      await navigator.clipboard.writeText(target);
      setCopied(true);
      window.setTimeout(() => {
        setCopied(false);
      }, 1500);
    } catch {
      setError("浏览器拒绝了剪贴板访问，请手动选择文本复制");
    }
  };

  return (
    <div className="flex min-h-0 flex-1" data-testid="writing-translate">
      <section className="flex min-w-0 flex-1 flex-col border-r border-border bg-surface">
        <header className="flex h-11 shrink-0 items-center gap-2 border-b border-border px-4">
          <Languages className="size-4 text-ink-2" aria-hidden />
          <h2 className="text-[var(--text-sm)] font-medium text-ink">中文原稿</h2>
          <span className="ml-auto text-[var(--text-xs)] text-ink-2">
            {source.length} / {LIMIT}
          </span>
        </header>
        <textarea
          value={source}
          onChange={(event) => {
            setSource(event.target.value);
          }}
          maxLength={LIMIT}
          aria-label="中文原稿"
          data-testid="translate-source"
          placeholder="粘贴中文摘要或正文…"
          className="app-scroll min-h-0 flex-1 resize-none bg-surface p-5 font-read text-[var(--text-base)] leading-relaxed text-ink outline-none placeholder:text-ink-2"
        />
        <div className="flex shrink-0 items-center gap-2 border-t border-border p-3">
          <Button
            variant="primary"
            data-testid="translate-run"
            disabled={!source.trim() || busy}
            loading={busy}
            onClick={() => {
              void translate();
            }}
          >
            {busy ? "翻译中…" : "一键翻译"}
          </Button>
          <span className="text-[11px] leading-relaxed text-ink-2">
            公式、代码与 [n] 引用保持原样；术语若在译文中消失会自动重试一次。
          </span>
        </div>
      </section>

      <section className="flex min-w-0 flex-1 flex-col bg-surface-2">
        <header className="flex h-11 shrink-0 items-center gap-2 border-b border-border px-4">
          <h2 className="text-[var(--text-sm)] font-medium text-ink">Academic English</h2>
          {cached && <span className="rounded bg-surface px-1.5 py-0.5 text-[11px] text-ink-2">缓存</span>}
          <div className="ml-auto flex gap-1">
            <Button size="sm" variant="ghost" data-testid="translate-copy" disabled={!target} onClick={() => { void copy(); }}>
              {copied ? <Check className="size-3.5" aria-hidden /> : <Clipboard className="size-3.5" aria-hidden />}
              {copied ? "已复制" : "复制"}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={!target}
              onClick={() => {
                setTarget("");
                setCached(false);
              }}
            >
              <RotateCcw className="size-3.5" aria-hidden />
              清空
            </Button>
          </div>
        </header>
        <div className="app-scroll min-h-0 flex-1 p-5">
          {busy && !target ? (
            <div className="flex h-full flex-col gap-3" aria-busy>
              <div className="h-4 w-full animate-pulse rounded bg-surface" />
              <div className="h-4 w-11/12 animate-pulse rounded bg-surface" />
              <div className="h-4 w-4/5 animate-pulse rounded bg-surface" />
            </div>
          ) : target ? (
            <p className="whitespace-pre-wrap font-read text-[var(--text-base)] leading-relaxed text-ink" data-testid="translate-target">
              {target}
            </p>
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
              <Languages className="size-6 text-ink-2" aria-hidden />
              <p className="text-[var(--text-md)] font-medium text-ink">译文会显示在这里</p>
              <p className="max-w-[36ch] text-[var(--text-sm)] text-ink-2">
                中文学术语体 → 英文论文语体；完整长文请使用阅读台的整篇翻译。
              </p>
            </div>
          )}
          {busy && target && (
            <p className="mt-3 flex items-center gap-1.5 text-[var(--text-xs)] text-ink-2">
              <Loader2 className="size-3.5 animate-spin" aria-hidden />
              正在重新翻译…
            </p>
          )}
          {error && <p className="mt-3 rounded-control bg-danger/10 p-2 text-[var(--text-xs)] text-danger-text">{error}</p>}
        </div>
      </section>
    </div>
  );
}
