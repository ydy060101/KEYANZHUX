import { ExternalLink, FileText, MessageSquareQuote, Plus, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Button } from "@/design/Button";
import { EmptyState, ErrorState, Skeleton } from "@/design/States";
import { useDocuments } from "@/features/library/api";
import { cn } from "@/lib/cn";
import { QaChat } from "./QaChat";
import { ScopePicker } from "./ScopePicker";
import {
  readerHref,
  type QaAnchor,
  type QaMode,
  type QaScope,
  type QaTurn,
} from "./api";
import { newId, sessionTitle, useQaHistory, type QaSession } from "./history";

/**
 * `/qa` (02 §4.3): scope and mode on top, the conversation in the middle, a
 * PDF split pane on the right when a source chip is opened, and real
 * conversation history on the left. History is local because the contract has
 * no session endpoint; it holds only turns this browser produced.
 */
export function QAPage() {
  const documentsQuery = useDocuments({ query: "", status: "ready", tag: "" });
  const documents = useMemo(() => documentsQuery.data?.items ?? [], [documentsQuery.data]);
  const docTitles = useMemo(
    () => Object.fromEntries(documents.map((doc) => [doc.id, doc.title])),
    [documents],
  );
  const sessions = useQaHistory((state) => state.sessions);
  const upsert = useQaHistory((state) => state.upsert);
  const remove = useQaHistory((state) => state.remove);
  const navigate = useNavigate();

  const [activeId, setActiveId] = useState("new");
  const [sessionId, setSessionId] = useState(newId);
  const [scope, setScope] = useState<QaScope>({ type: "all", doc_ids: [] });
  const [mode, setMode] = useState<QaMode>("qa");
  const [anchor, setAnchor] = useState<QaAnchor | null>(null);

  const active = activeId === "new" ? null : (sessions.find((item) => item.id === activeId) ?? null);

  useEffect(() => {
    if (scope.type !== "doc" || scope.doc_ids.length > 0) return;
    const first = documents[0];
    if (!first) return;
    setScope({ type: "doc", doc_ids: [first.id] });
  }, [scope, documents]);

  const startNew = useCallback(() => {
    setSessionId(newId());
    setActiveId("new");
    setScope({ type: "all", doc_ids: [] });
    setMode("qa");
    setAnchor(null);
  }, []);

  const selectSession = (session: QaSession) => {
    setActiveId(session.id);
    setScope(session.scope);
    setMode(session.mode);
    setAnchor(null);
  };

  const deleteSession = (id: string) => {
    remove(id);
    if (activeId === id || (activeId === "new" && id === sessionId)) startNew();
  };

  const handleTurns = useCallback(
    (turns: QaTurn[]) => {
      if (turns.length === 0) return;
      const id = activeId === "new" ? sessionId : activeId;
      const existing = sessions.find((item) => item.id === id);
      upsert({
        id,
        title: sessionTitle(turns),
        createdAt: existing?.createdAt ?? turns[0]?.createdAt ?? new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        scope,
        mode,
        turns,
      });
    },
    [activeId, sessionId, sessions, scope, mode, upsert],
  );

  const canCompare = scope.type === "all" ? documents.length >= 2 : scope.doc_ids.length >= 2;
  const blocked =
    scope.type !== "all" && scope.doc_ids.length === 0
      ? "请先选择至少一篇文献"
      : mode === "compare" && !canCompare
        ? "对比至少需要两篇文献"
        : undefined;

  const switchMode = (next: QaMode) => {
    if (next === "compare" && scope.type === "doc") setScope({ type: "all", doc_ids: [] });
    setMode(next);
  };

  const openAnchor = (value: QaAnchor) => {
    const wide =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(min-width: 1280px)").matches;
    if (wide) {
      setAnchor(value);
      return;
    }
    void navigate(readerHref(value));
  };

  return (
    <div className="flex h-full min-h-0">
      <HistorySidebar
        sessions={sessions}
        activeId={activeId === "new" ? sessionId : activeId}
        onNew={startNew}
        onSelect={selectSession}
        onRemove={deleteSession}
      />

      <section className="flex min-w-0 flex-1 flex-col">
        <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border px-4 py-2.5">
          <ScopePicker
            scope={scope}
            onChange={setScope}
            documents={documents}
            loading={documentsQuery.isPending}
            error={documentsQuery.isError ? documentsQuery.error.message : null}
            onRetry={() => {
              void documentsQuery.refetch();
            }}
            max={mode === "compare" ? 5 : undefined}
          />
          <div className="ml-auto flex rounded-control border border-border p-0.5" role="group" aria-label="模式">
            {(
              [
                ["qa", "问答"],
                ["compare", "对比"],
              ] as const
            ).map(([key, label]) => {
              const disabled = key === "compare" && !canCompare;
              return (
                <button
                  key={key}
                  type="button"
                  aria-pressed={mode === key}
                  disabled={disabled}
                  title={disabled ? "对比至少需要两篇已解析文献" : undefined}
                  onClick={() => {
                    switchMode(key);
                  }}
                  className={cn(
                    "rounded-[6px] px-3 py-1 text-[var(--text-sm)] transition-colors duration-[--dur-fast]",
                    mode === key ? "bg-surface-2 font-medium text-ink" : "text-ink-2 hover:text-ink",
                    disabled && "cursor-not-allowed opacity-40 hover:text-ink-2",
                  )}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>

        {documentsQuery.isError ? (
          <ErrorState
            message="文献列表加载失败"
            detail={documentsQuery.error.message}
            onRetry={() => {
              void documentsQuery.refetch();
            }}
          />
        ) : documentsQuery.isSuccess && documents.length === 0 ? (
          <EmptyState
            title="资料库还没有已解析的文献"
            description="问答需要至少一篇解析完成的 PDF。先上传文献，等解析结束后再回来。"
            icon={<FileText className="size-6" aria-hidden />}
            action={
              <Link
                to="/library"
                className="rounded-control bg-primary px-4 py-2 text-[var(--text-sm)] font-medium text-white"
              >
                去资料库
              </Link>
            }
          />
        ) : documentsQuery.isPending ? (
          <div className="space-y-3 p-6">
            <Skeleton className="h-8 w-48" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-16 w-2/3" />
          </div>
        ) : (
          <QaChat
            key={activeId === "new" ? sessionId : activeId}
            scope={scope}
            mode={mode}
            docTitles={docTitles}
            onOpenAnchor={openAnchor}
            initialTurns={active?.turns ?? []}
            onTurnsChange={handleTurns}
            disabledReason={blocked}
          />
        )}
      </section>

      {anchor && (
        <AnchorPreview
          anchor={anchor}
          title={docTitles[anchor.doc_id] ?? anchor.doc_id}
          onClose={() => {
            setAnchor(null);
          }}
        />
      )}
    </div>
  );
}

function HistorySidebar({
  sessions,
  activeId,
  onNew,
  onSelect,
  onRemove,
}: {
  sessions: QaSession[];
  activeId: string;
  onNew: () => void;
  onSelect: (session: QaSession) => void;
  onRemove: (id: string) => void;
}) {
  return (
    <aside className="flex w-[220px] shrink-0 flex-col border-r border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-3 py-2.5">
        <span className="text-[var(--text-sm)] font-medium text-ink">历史会话</span>
        <button
          type="button"
          aria-label="新建会话"
          title="新建会话"
          onClick={onNew}
          className="rounded p-1 text-ink-2 hover:bg-surface-2 hover:text-ink"
        >
          <Plus className="size-4" aria-hidden />
        </button>
      </div>
      {sessions.length === 0 ? (
        <p className="px-4 py-6 text-center text-[var(--text-sm)] text-ink-2">还没有历史会话</p>
      ) : (
        <ul className="app-scroll min-h-0 flex-1 p-2">
          {sessions.map((session) => (
            <li key={session.id} className="group relative">
              <button
                type="button"
                aria-current={activeId === session.id ? "true" : undefined}
                onClick={() => {
                  onSelect(session);
                }}
                className={cn(
                  "w-full rounded-control px-2.5 py-2 pr-8 text-left text-[var(--text-sm)]",
                  activeId === session.id
                    ? "bg-surface-2 font-medium text-ink"
                    : "text-ink-2 hover:bg-surface-2 hover:text-ink",
                )}
              >
                <span className="line-clamp-2">{session.title}</span>
                <span className="mt-0.5 block text-[var(--text-xs)] text-ink-2">
                  {new Date(session.updatedAt).toLocaleDateString("zh-CN", {
                    month: "2-digit",
                    day: "2-digit",
                  })}
                </span>
              </button>
              <button
                type="button"
                aria-label={`删除会话：${session.title}`}
                onClick={() => {
                  onRemove(session.id);
                }}
                className="absolute right-1 top-1.5 rounded p-1 text-ink-2 opacity-0 hover:text-danger-text group-hover:opacity-100 focus-visible:opacity-100"
              >
                <Trash2 className="size-3.5" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="border-t border-border p-2">
        <Button variant="secondary" size="sm" className="w-full" onClick={onNew}>
          <MessageSquareQuote className="size-3.5" aria-hidden />
          新建会话
        </Button>
      </div>
    </aside>
  );
}

function AnchorPreview({
  anchor,
  title,
  onClose,
}: {
  anchor: QaAnchor;
  title: string;
  onClose: () => void;
}) {
  return (
    <aside
      className="hidden w-[440px] shrink-0 flex-col border-l border-border bg-surface xl:flex"
      data-testid="qa-preview"
    >
      <div className="flex h-10 shrink-0 items-center gap-2 border-b border-border px-3">
        <FileText className="size-3.5 shrink-0 text-ink-2" aria-hidden />
        <span className="min-w-0 flex-1 truncate text-[var(--text-sm)] text-ink" title={title}>
          {title}
        </span>
        <span className="shrink-0 text-[var(--text-xs)] text-ink-2">第 {anchor.page} 页</span>
        <a
          href={readerHref(anchor)}
          target="_blank"
          rel="noreferrer"
          aria-label="在阅读台打开"
          title="在阅读台打开"
          className="rounded p-1 text-ink-2 hover:bg-surface-2 hover:text-ink"
        >
          <ExternalLink className="size-3.5" aria-hidden />
        </a>
        <button
          type="button"
          aria-label="关闭原文预览"
          onClick={onClose}
          className="rounded p-1 text-ink-2 hover:bg-surface-2 hover:text-ink"
        >
          <X className="size-4" aria-hidden />
        </button>
      </div>
      <iframe
        title="原文锚点"
        src={readerHref(anchor, true)}
        className="min-h-0 w-full flex-1 border-0"
        data-testid="qa-preview-frame"
      />
    </aside>
  );
}
