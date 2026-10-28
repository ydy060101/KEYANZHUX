import katex from "katex";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * A small Markdown renderer for the outline editor (T7.5).
 *
 * The backend returns a controlled subset — three headings, paragraphs and
 * `\cite{key}` — so a full Markdown library would be dead weight. Inline math
 * goes through KaTeX; citations become buttons that select the matching card
 * in the verification panel. Text is never inserted as HTML: only KaTeX's own
 * output uses `dangerouslySetInnerHTML`.
 */

interface MarkdownProps {
  markdown: string;
  selectedKey?: string | null;
  onCite?: (key: string) => void;
}

function math(source: string, display: boolean): ReactNode {
  const html = katex.renderToString(source, {
    displayMode: display,
    throwOnError: false,
    strict: false,
    output: "html",
  });
  return <span className={display ? "my-2 block overflow-x-auto text-center" : "inline-block"} dangerouslySetInnerHTML={{ __html: html }} />;
}

function inline(source: string, onCite?: (key: string) => void, selectedKey?: string | null): ReactNode[] {
  const pattern = /\\cite\{([^}]*)\}|\$([^$\n]+)\$|\*\*([^*]+)\*\*|`([^`]+)`|\[待补充\]/g;
  const nodes: ReactNode[] = [];
  let cursor = 0;
  let serial = 0;
  for (const match of source.matchAll(pattern)) {
    const index = match.index;
    if (index > cursor) nodes.push(source.slice(cursor, index));
    serial += 1;
    if (match[1] !== undefined) {
      const keys = match[1].split(",").map((key) => key.trim()).filter(Boolean);
      nodes.push(
        <span key={`cite-${serial}`} className="inline-flex flex-wrap gap-1 align-baseline">
          {keys.map((key) => (
            <button
              key={`${key}-${serial}`}
              type="button"
              data-citation-key={key}
              onClick={() => {
                onCite?.(key);
              }}
              className={cn(
                "rounded border px-1.5 py-0.5 font-mono text-[var(--text-xs)] transition-colors duration-[--dur-fast]",
                selectedKey === key
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border bg-surface-2 text-ink-2 hover:border-primary hover:text-primary",
              )}
              title={`定位引用 ${key}`}
            >
              {key}
            </button>
          ))}
        </span>,
      );
    } else if (match[2] !== undefined) {
      nodes.push(<span key={`math-${serial}`}>{math(match[2], false)}</span>);
    } else if (match[3] !== undefined) {
      nodes.push(
        <strong key={`bold-${serial}`} className="font-semibold text-ink">
          {inline(match[3], onCite, selectedKey)}
        </strong>,
      );
    } else if (match[4] !== undefined) {
      nodes.push(
        <code key={`code-${serial}`} className="rounded bg-surface-2 px-1 py-0.5 font-mono text-[var(--text-sm)]">
          {match[4]}
        </code>,
      );
    } else {
      nodes.push(
        <span key={`missing-${serial}`} className="rounded bg-warn/15 px-1 py-0.5 text-[var(--text-xs)] text-warn-text">
          [待补充]
        </span>,
      );
    }
    cursor = index + match[0].length;
  }
  if (cursor < source.length) nodes.push(source.slice(cursor));
  return nodes;
}

function headingNode(
  level: number,
  body: string,
  key: string,
  onCite?: (key: string) => void,
  selectedKey?: string | null,
): ReactNode {
  const className =
    level === 1
      ? "mt-2 text-[var(--text-xl)] font-semibold leading-tight text-ink"
      : level === 2
        ? "mt-6 border-b border-border pb-2 text-[var(--text-lg)] font-semibold text-ink"
        : "mt-4 text-[var(--text-md)] font-semibold text-ink";
  return (
    <p key={key} className={className} role="heading" aria-level={level}>
      {inline(body, onCite, selectedKey)}
    </p>
  );
}

function displayMathNode(source: string, key: string): ReactNode {
  return (
    <div key={key} className="overflow-x-auto py-1">
      {math(source, true)}
    </div>
  );
}

function renderBlocks(
  markdown: string,
  onCite?: (key: string) => void,
  selectedKey?: string | null,
): ReactNode[] {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let paragraph: string[] = [];
  let list: string[] = [];

  const flushParagraph = () => {
    const value = paragraph.join(" ").trim();
    if (value) {
      blocks.push(
        <p key={`p-${blocks.length}`} className="text-[var(--text-base)] leading-relaxed text-ink">
          {inline(value, onCite, selectedKey)}
        </p>,
      );
    }
    paragraph = [];
  };
  const flushList = () => {
    if (list.length > 0) {
      blocks.push(
        <ul key={`ul-${blocks.length}`} className="list-disc space-y-1 pl-5 text-[var(--text-base)] leading-relaxed text-ink">
          {list.map((item, index) => (
            <li key={`${index}-${item.slice(0, 12)}`}>{inline(item, onCite, selectedKey)}</li>
          ))}
        </ul>,
      );
    }
    list = [];
  };
  const flush = () => {
    flushParagraph();
    flushList();
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("```")) {
      flush();
      continue;
    }
    const heading = /^(#{1,3})\s+(.*)$/.exec(trimmed);
    if (heading) {
      flush();
      blocks.push(headingNode(heading[1]?.length ?? 1, heading[2] ?? "", `h-${blocks.length}`, onCite, selectedKey));
      continue;
    }
    const item = /^\s*[-*]\s+(.*)$/.exec(line);
    if (item) {
      flushParagraph();
      list.push(item[1] ?? "");
      continue;
    }
    const display = /^\$\$(.+)\$\$$/.exec(trimmed);
    if (display) {
      flush();
      blocks.push(displayMathNode(display[1] ?? "", `d-${blocks.length}`));
      continue;
    }
    flushList();
    paragraph.push(trimmed);
  }
  flush();
  return blocks;
}

export function MarkdownPreview({ markdown, selectedKey, onCite }: MarkdownProps) {
  const blocks = renderBlocks(markdown, onCite, selectedKey);
  if (blocks.length === 0) {
    return <p className="text-[var(--text-sm)] text-ink-2">还没有正文。</p>;
  }
  return (
    <article className="space-y-3" data-testid="outline-preview">
      {blocks}
    </article>
  );
}
