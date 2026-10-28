import { ChevronLeft, ChevronRight, ExternalLink } from "lucide-react";
import type { PDFDocumentProxy } from "pdfjs-dist";
import { useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import { ErrorState, Skeleton } from "@/design/States";
import { useTheme } from "@/design/theme";
import { loadPdf, pageSize as measurePage } from "./pdf";
import { PageView, type PageSize } from "./PageView";
import { clampZoom } from "./readerStore";
import { parseBbox } from "./anchorQuery";

const noop = (): void => undefined;

/**
 * A single-page PDF view for the QA split pane (02 §4.3).
 *
 * It lives outside the app shell so the iframe holds only the page, not a
 * second navigation and top bar. It renders one page at a time and draws the
 * anchor's bbox with the reader's own `--hl` box, so the highlight in the split
 * pane and in the full reader look the same.
 */
export function ReaderEmbed() {
  const { docId = "" } = useParams();
  const [params] = useSearchParams();
  const anchorPage = Math.max(1, Number(params.get("page") ?? "1") || 1);
  const bbox = parseBbox(params.get("bbox"));

  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [page, setPage] = useState(anchorPage);
  const [size, setSize] = useState<PageSize>({ width: 612, height: 792 });
  const [zoom, setZoom] = useState(100);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const hostRef = useRef<HTMLDivElement | null>(null);
  const initTheme = useTheme((state) => state.init);

  useEffect(() => {
    initTheme();
  }, [initTheme]);

  useEffect(() => {
    if (!docId) return;
    const cancelled = { current: false };
    setDoc(null);
    setError(null);
    void loadPdf(docId)
      .then((loaded) => {
        if (cancelled.current) return;
        setDoc(loaded);
        setPage(Math.min(loaded.numPages, anchorPage));
      })
      .catch((reason: unknown) => {
        if (cancelled.current) return;
        setError(reason instanceof Error ? reason.message : "PDF 加载失败");
      });
    return () => {
      cancelled.current = true;
    };
  }, [docId, anchorPage, attempt]);

  useEffect(() => {
    if (!doc) return;
    const cancelled = { current: false };
    void measurePage(doc, page)
      .then((measured) => {
        if (!cancelled.current) setSize(measured);
      })
      .catch(() => {
        // The page box keeps its previous size; the page still renders.
      });
    return () => {
      cancelled.current = true;
    };
  }, [doc, page]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const fit = () => {
      const available = host.clientWidth - 32;
      if (available <= 0) return;
      setZoom(clampZoom(Math.floor((available / size.width) * 100)));
    };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(host);
    return () => {
      observer.disconnect();
    };
  }, [doc, size.width]);

  if (!docId) {
    return <ErrorState message="没有要预览的文献" />;
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface-2">
      <div className="flex h-9 shrink-0 items-center gap-2 border-b border-border bg-surface px-2 text-[var(--text-xs)] text-ink-2">
        <button
          type="button"
          aria-label="上一页"
          disabled={page <= 1}
          onClick={() => {
            setPage((value) => Math.max(1, value - 1));
          }}
          className="rounded p-1 hover:bg-surface-2 disabled:opacity-40"
        >
          <ChevronLeft className="size-4" aria-hidden />
        </button>
        <span data-testid="embed-page">
          第 {page} / {doc?.numPages ?? "…"} 页
        </span>
        <button
          type="button"
          aria-label="下一页"
          disabled={!doc || page >= doc.numPages}
          onClick={() => {
            setPage((value) => value + 1);
          }}
          className="rounded p-1 hover:bg-surface-2 disabled:opacity-40"
        >
          <ChevronRight className="size-4" aria-hidden />
        </button>
        <a
          href={`/reader/${encodeURIComponent(docId)}?page=${page}${
            page === anchorPage && bbox ? `&bbox=${bbox.join(",")}` : ""
          }`}
          target="_blank"
          rel="noreferrer"
          className="ml-auto flex items-center gap-1 rounded px-2 py-1 text-primary hover:bg-surface-2"
        >
          <ExternalLink className="size-3" aria-hidden />
          阅读台
        </a>
      </div>

      {error ? (
        <ErrorState
          message="原文预览加载失败"
          detail={error}
          onRetry={() => {
            setAttempt((value) => value + 1);
          }}
        />
      ) : (
        <div ref={hostRef} className="min-h-0 flex-1 overflow-auto p-4">
          {doc ? (
            <PageView
              doc={doc}
              pageNumber={page}
              size={size}
              active
              zoom={zoom}
              highlight={page === anchorPage && bbox ? bbox : null}
              onSize={noop}
              onActive={noop}
              register={noop}
            />
          ) : (
            <div className="flex justify-center">
              <Skeleton className="h-[70vh] w-[520px] max-w-full" />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
