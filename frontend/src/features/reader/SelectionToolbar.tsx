import { Copy, Highlighter, Languages, MessageSquareQuote } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/design/Button";

/**
 * The floating toolbar over a text selection (02 §4.2).
 *
 * It sits where the selection ends rather than at the pointer, so it does not
 * cover the words being read, and it disappears on the next click anywhere.
 * Translate and ask are wired in T4.1 / T3.5; until then they say so instead
 * of pretending to work (H02).
 */
export interface SelectionToolbarProps {
  onTranslate: (text: string) => void;
  onAsk: (text: string) => void;
  onHighlight: (text: string) => void;
}

interface Position {
  x: number;
  y: number;
  text: string;
}

export function SelectionToolbar({ onTranslate, onAsk, onHighlight }: SelectionToolbarProps) {
  const [position, setPosition] = useState<Position | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    function clear() {
      const selection = window.getSelection();
      if (!selection || selection.isCollapsed) setPosition(null);
    }
    function onSelectionEnd(event: MouseEvent) {
      const selection = window.getSelection();
      const text = selection?.toString().trim() ?? "";
      if (!selection || selection.isCollapsed || text.length < 2) {
        setPosition(null);
        return;
      }
      const rect = selection.getRangeAt(0).getBoundingClientRect();
      setPosition({ x: rect.left + rect.width / 2, y: rect.bottom + 8, text });
      setCopied(false);
      event.stopPropagation();
    }
    document.addEventListener("mouseup", onSelectionEnd);
    document.addEventListener("selectionchange", clear);
    return () => {
      document.removeEventListener("mouseup", onSelectionEnd);
      document.removeEventListener("selectionchange", clear);
    };
  }, []);

  if (!position) return null;

  return (
    <div
      role="toolbar"
      aria-label="划词工具"
      className="fixed z-30 flex -translate-x-1/2 items-center gap-0.5 rounded-card border border-border bg-surface p-1 shadow-lg"
      style={{ left: position.x, top: position.y }}
      onMouseDown={(event) => {
        event.preventDefault();
      }}
    >
      <Button size="sm" variant="ghost" onClick={() => { onTranslate(position.text); }}>
        <Languages className="size-3.5" aria-hidden />
        翻译
      </Button>
      <Button size="sm" variant="ghost" onClick={() => { onAsk(position.text); }}>
        <MessageSquareQuote className="size-3.5" aria-hidden />
        提问
      </Button>
      <Button
        size="sm"
        variant="ghost"
        onClick={() => {
          void navigator.clipboard.writeText(position.text).then(() => {
            setCopied(true);
          });
        }}
      >
        <Copy className="size-3.5" aria-hidden />
        {copied ? "已复制" : "复制"}
      </Button>
      <Button size="sm" variant="ghost" onClick={() => { onHighlight(position.text); }}>
        <Highlighter className="size-3.5" aria-hidden />
        高亮
      </Button>
    </div>
  );
}
