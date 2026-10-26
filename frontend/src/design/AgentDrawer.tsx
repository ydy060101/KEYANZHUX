import { Send, Sparkles, X } from "lucide-react";
import { useState } from "react";

import { useUi } from "@/app/ui";
import { Button } from "./Button";

/** Right-hand assistant drawer, reachable from any page with ⌘J (02 §3). */
export function AgentDrawer() {
  const open = useUi((s) => s.agentOpen);
  const setOpen = useUi((s) => s.setAgentOpen);
  const [draft, setDraft] = useState("");

  if (!open) return null;

  return (
    <aside
      aria-label="Agent 助手"
      className="flex w-[380px] shrink-0 flex-col border-l border-border bg-surface"
    >
      <div className="flex h-[var(--topbar-height)] items-center gap-2 border-b border-border px-4">
        <Sparkles className="size-4 text-primary" strokeWidth={1.75} aria-hidden />
        <span className="text-[var(--text-base)] font-medium">Agent 助手</span>
        <button
          type="button"
          aria-label="关闭 Agent 助手"
          onClick={() => {
            setOpen(false);
          }}
          className="ml-auto rounded p-1 text-ink-2 hover:text-ink"
        >
          <X className="size-4" aria-hidden />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        <p className="text-[var(--text-sm)] text-ink-2">
          带着当前页面的上下文提问。打开一篇文献后，问题会自动带上该文献作为检索范围。
        </p>
      </div>
      <form
        className="flex items-end gap-2 border-t border-border p-3"
        onSubmit={(event) => {
          event.preventDefault();
          setDraft("");
        }}
      >
        <textarea
          value={draft}
          onChange={(event) => {
            setDraft(event.target.value);
          }}
          rows={2}
          placeholder="问点什么…"
          aria-label="向 Agent 提问"
          className="flex-1 resize-none rounded-control border border-border bg-surface-2 px-3 py-2 text-[var(--text-base)] text-ink outline-none placeholder:text-ink-2"
        />
        <Button type="submit" variant="primary" size="icon" aria-label="发送" disabled={!draft.trim()}>
          <Send className="size-4" aria-hidden />
        </Button>
      </form>
    </aside>
  );
}
