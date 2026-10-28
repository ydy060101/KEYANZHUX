import Editor, { loader } from "@monaco-editor/react";
import { useEffect, useState } from "react";

import { useTheme } from "@/design/theme";
import { cn } from "@/lib/cn";

/**
 * The figure studio's script editor (02 §4.6, T7.5).
 *
 * Monaco is loaded from the installed package, not a CDN: the demo host must
 * work without outbound access, and the loader is configured only after both
 * the editor and its single worker are in the bundle. While that chunk loads
 * (and if it ever fails) the same text stays editable in a plain textarea, so
 * the workspace never offers a dead control.
 */
export interface ScriptEditorProps {
  value: string;
  onChange: (value: string) => void;
  language: string;
  ariaLabel: string;
  className?: string;
}

interface MonacoEnvironment {
  getWorker: () => Worker;
}

interface WorkerModule {
  default: new () => Worker;
}

export function ScriptEditor({ value, onChange, language, ariaLabel, className }: ScriptEditorProps) {
  const resolved = useTheme((state) => state.resolved);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const [monaco, worker] = await Promise.all([
          import("monaco-editor"),
          import("monaco-editor/editor/editor.worker?worker") as Promise<WorkerModule>,
        ]);
        (globalThis as unknown as { MonacoEnvironment?: MonacoEnvironment }).MonacoEnvironment = {
          getWorker: () => new worker.default(),
        };
        loader.config({ monaco });
        setReady(true);
      } catch {
        // Keeping the textarea is the fallback; the script is never lost.
      }
    })();
  }, []);

  if (!ready) {
    return (
      <textarea
        aria-label={ariaLabel}
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
        }}
        spellCheck={false}
        className={cn(
          "app-scroll h-full w-full resize-none bg-surface p-3 font-mono text-[var(--text-sm)] leading-relaxed text-ink outline-none",
          className,
        )}
      />
    );
  }

  return (
    <div className={cn("h-full min-h-0 overflow-hidden", className)} data-testid="monaco-editor">
      <Editor
        value={value}
        language={language}
        theme={resolved === "dark" ? "vs-dark" : "light"}
        onChange={(next) => {
          onChange(next ?? "");
        }}
        options={{
          ariaLabel,
          minimap: { enabled: false },
          fontSize: 13,
          lineNumbers: "on",
          wordWrap: "on",
          scrollBeyondLastLine: false,
          automaticLayout: true,
          tabSize: 2,
          padding: { top: 12, bottom: 12 },
        }}
      />
    </div>
  );
}
