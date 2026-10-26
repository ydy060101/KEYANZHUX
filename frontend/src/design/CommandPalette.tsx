import { BookOpen, Compass, GitFork, Library, MessageSquareQuote, PenLine, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useUi } from "@/app/ui";
import { cn } from "@/lib/cn";

interface Command {
  id: string;
  label: string;
  hint: string;
  run: () => void;
}

const ROUTES = [
  { to: "/library", label: "资料库", icon: Library },
  { to: "/reader", label: "阅读", icon: BookOpen },
  { to: "/qa", label: "问答", icon: MessageSquareQuote },
  { to: "/discover", label: "发现", icon: Compass },
  { to: "/graph", label: "图谱", icon: GitFork },
  { to: "/writing", label: "写作", icon: PenLine },
] as const;

/** ⌘K palette: jump to any page or trigger a common action (02 §3). */
export function CommandPalette() {
  const open = useUi((s) => s.commandOpen);
  const setOpen = useUi((s) => s.setCommandOpen);
  const toggleAgent = useUi((s) => s.toggleAgent);
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const commands = useMemo<Command[]>(
    () => [
      ...ROUTES.map((r) => ({
        id: `go:${r.to}`,
        label: `前往${r.label}`,
        hint: r.to,
        run: () => {
          navigate(r.to);
        },
      })),
      {
        id: "agent:open",
        label: "打开 Agent 助手",
        hint: "⌘J",
        run: () => {
          toggleAgent();
        },
      },
    ],
    [navigate, toggleAgent],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands;
    return commands.filter((c) => c.label.toLowerCase().includes(q) || c.hint.toLowerCase().includes(q));
  }, [commands, query]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
      inputRef.current?.focus();
    }
  }, [open]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen(!useUi.getState().commandOpen);
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "j") {
        event.preventDefault();
        toggleAgent();
      }
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [setOpen, toggleAgent]);

  if (!open) return null;

  const choose = (command: Command | undefined) => {
    if (!command) return;
    command.run();
    setOpen(false);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/30 p-4 pt-[15vh]"
      role="dialog"
      aria-modal="true"
      aria-label="命令面板"
      onMouseDown={() => {
        setOpen(false);
      }}
    >
      <div
        className="w-full max-w-[560px] overflow-hidden rounded-dialog border border-border bg-surface shadow-lg"
        onMouseDown={(event) => {
          event.stopPropagation();
        }}
      >
        <div className="flex items-center gap-2 border-b border-border px-4 py-3">
          <Search className="size-4 text-ink-2" strokeWidth={1.75} aria-hidden />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setActive(0);
            }}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setActive((i) => Math.min(i + 1, filtered.length - 1));
              } else if (event.key === "ArrowUp") {
                event.preventDefault();
                setActive((i) => Math.max(i - 1, 0));
              } else if (event.key === "Enter") {
                choose(filtered[active]);
              }
            }}
            placeholder="搜索或输入命令…"
            aria-label="搜索命令"
            className="w-full bg-transparent text-[var(--text-base)] text-ink outline-none placeholder:text-ink-2"
          />
        </div>
        <ul className="max-h-[320px] overflow-y-auto p-1" role="listbox">
          {filtered.length === 0 && (
            <li className="px-3 py-6 text-center text-[var(--text-sm)] text-ink-2">没有匹配的命令</li>
          )}
          {filtered.map((command, index) => (
            <li key={command.id}>
              <button
                type="button"
                role="option"
                aria-selected={index === active}
                onMouseEnter={() => {
                  setActive(index);
                }}
                onClick={() => {
                  choose(command);
                }}
                className={cn(
                  "flex w-full items-center gap-2 rounded-control px-3 py-2 text-left text-[var(--text-base)]",
                  index === active ? "bg-surface-2 text-ink" : "text-ink-2",
                )}
              >
                {command.label}
                <span className="ml-auto text-[var(--text-xs)] text-ink-2">{command.hint}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
