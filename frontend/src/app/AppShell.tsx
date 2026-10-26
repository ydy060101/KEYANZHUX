import {
  BookOpen,
  Compass,
  GitFork,
  Library,
  MessageSquareQuote,
  Moon,
  PenLine,
  Search,
  Sun,
  User,
} from "lucide-react";
import { useEffect } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { cn } from "@/lib/cn";
import { useTheme, type ThemeMode } from "@/design/theme";

const NAV = [
  { to: "/library", label: "资料库", icon: Library },
  { to: "/reader", label: "阅读", icon: BookOpen },
  { to: "/qa", label: "问答", icon: MessageSquareQuote },
  { to: "/discover", label: "发现", icon: Compass },
  { to: "/graph", label: "图谱", icon: GitFork },
  { to: "/writing", label: "写作", icon: PenLine },
] as const;

const THEME_CYCLE: ThemeMode[] = ["light", "dark", "system"];
const THEME_LABEL: Record<ThemeMode, string> = { light: "浅色", dark: "深色", system: "跟随系统" };

function ThemeToggle() {
  const mode = useTheme((s) => s.mode);
  const setMode = useTheme((s) => s.setMode);
  const next = THEME_CYCLE[(THEME_CYCLE.indexOf(mode) + 1) % THEME_CYCLE.length] ?? "system";
  const Icon = mode === "dark" ? Moon : Sun;
  return (
    <button
      type="button"
      onClick={() => {
        setMode(next);
      }}
      aria-label={`切换主题，当前${THEME_LABEL[mode]}`}
      title={`主题：${THEME_LABEL[mode]}`}
      className="flex size-9 items-center justify-center rounded-control text-ink-2 transition-colors duration-[--dur-fast] hover:bg-surface-2 hover:text-ink"
    >
      <Icon className="size-[18px]" strokeWidth={1.75} aria-hidden />
    </button>
  );
}

export function AppShell() {
  const init = useTheme((s) => s.init);
  const location = useLocation();

  useEffect(() => {
    init();
  }, [init]);

  return (
    <div className="flex h-full bg-bg text-ink">
      <nav
        aria-label="主导航"
        className="flex w-[var(--nav-width)] shrink-0 flex-col border-r border-border bg-surface"
      >
        <div className="flex h-[var(--topbar-height)] items-center gap-2 px-4">
          <div className="flex size-7 items-center justify-center rounded-control bg-primary text-[var(--text-sm)] font-semibold text-white">
            科
          </div>
          <span className="text-[var(--text-base)] font-semibold">科研助手</span>
        </div>
        <ul className="flex flex-col gap-1 p-2">
          {NAV.map(({ to, label, icon: Icon }) => (
            <li key={to}>
              <NavLink
                to={to}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-2.5 rounded-control px-3 py-2 text-[var(--text-base)] transition-colors duration-[--dur-fast]",
                    isActive
                      ? "bg-surface-2 font-medium text-primary"
                      : "text-ink-2 hover:bg-surface-2 hover:text-ink",
                  )
                }
              >
                <Icon className="size-[18px] shrink-0" strokeWidth={1.75} aria-hidden />
                {label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-[var(--topbar-height)] shrink-0 items-center gap-3 border-b border-border bg-surface px-4">
          <button
            type="button"
            aria-label="全局搜索（⌘K）"
            className="flex h-9 min-w-0 flex-1 max-w-[420px] items-center gap-2 rounded-control border border-border bg-surface-2 px-3 text-[var(--text-sm)] text-ink-2 transition-colors duration-[--dur-fast] hover:text-ink"
          >
            <Search className="size-4 shrink-0" strokeWidth={1.75} aria-hidden />
            <span className="truncate">搜索文献、跳转页面…</span>
            <kbd className="ml-auto rounded border border-border px-1.5 py-0.5 text-[11px]">⌘K</kbd>
          </button>
          <div className="ml-auto flex items-center gap-1">
            <span className="flex items-center gap-1.5 rounded-control border border-border px-2 py-1 text-[var(--text-sm)] text-ink-2">
              <User className="size-3.5" strokeWidth={1.75} aria-hidden />
              default
            </span>
            <ThemeToggle />
          </div>
        </header>

        <main key={location.pathname} className="app-scroll flex-1">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
