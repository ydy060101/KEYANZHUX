import { create } from "zustand";

export type ThemeMode = "light" | "dark" | "system";

const STORAGE_KEY = "ra-theme";

function resolve(mode: ThemeMode): "light" | "dark" {
  if (mode !== "system") return mode;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function apply(mode: ThemeMode): void {
  if (typeof document === "undefined") return;
  document.documentElement.dataset["theme"] = resolve(mode);
}

interface ThemeState {
  mode: ThemeMode;
  resolved: "light" | "dark";
  setMode: (mode: ThemeMode) => void;
  init: () => void;
}

function readStored(): ThemeMode {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === "light" || raw === "dark" || raw === "system") return raw;
  } catch {
    // localStorage can throw in private mode; fall back to system.
  }
  return "system";
}

export const useTheme = create<ThemeState>((set, get) => ({
  mode: "system",
  resolved: "light",
  setMode: (mode) => {
    apply(mode);
    try {
      localStorage.setItem(STORAGE_KEY, mode);
    } catch {
      // Persisting the preference is a convenience, never a requirement.
    }
    set({ mode, resolved: resolve(mode) });
  },
  init: () => {
    const mode = readStored();
    apply(mode);
    set({ mode, resolved: resolve(mode) });
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
      if (get().mode === "system") {
        apply("system");
        set({ resolved: resolve("system") });
      }
    });
  },
}));
