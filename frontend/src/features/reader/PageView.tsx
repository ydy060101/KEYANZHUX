import type { PDFDocumentProxy } from "pdfjs-dist";
import { useEffect, useRef, type ReactNode } from "react";

import { scaleFor } from "./pdf";

/**
 * One page of the PDF (T2.6).
 *
 * Every page is a box of the right size, so the scroll height is correct
 * before anything renders and never jumps as pages appear. Only pages near
 * the viewport hold a bitmap (`active`), which is what keeps a 541-page book
 * from trying to keep 541 canvases in memory.
 */

export interface PageSize {
  width: number;
  height: number;
}

export interface PageViewProps {
  doc: PDFDocumentProxy;
  pageNumber: number;
  size: PageSize;
  active: boolean;
  zoom: number;
  highlight: [number, number, number, number] | null;
  onSize: (pageNumber: number, size: PageSize) => void;
  onActive: (pageNumber: number) => void;
  register: (pageNumber: number, node: HTMLDivElement | null) => void;
  /** Citation hit boxes drawn over the text layer (02 §4.2). */
  overlay?: ReactNode;
}

export function PageView({
  doc,
  pageNumber,
  size,
  active,
  zoom,
  highlight,
  onSize,
  onActive,
  register,
  overlay,
}: PageViewProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const textRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    register(pageNumber, hostRef.current);
    return () => {
      register(pageNumber, null);
    };
  }, [pageNumber, register]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) onActive(pageNumber);
      },
      { root: host.closest("[data-reader-scroll]"), rootMargin: "-40% 0px -40% 0px" },
    );
    observer.observe(host);
    return () => {
      observer.disconnect();
    };
  }, [pageNumber, onActive]);

  useEffect(() => {
    if (!active) return;
    // A ref rather than a `let`: the cleanup sets it, and TypeScript would
    // otherwise narrow it to `false` and call the guard dead code.
    const cancelled = { current: false };
    const canvas = canvasRef.current;
    const textLayer = textRef.current;
    if (!canvas || !textLayer) return;

    void (async () => {
      const { renderPage } = await import("./pdf");
      const rendered = await renderPage(doc, pageNumber, zoom);
      if (cancelled.current) return;
      onSize(pageNumber, { width: rendered.width, height: rendered.height });
      canvas.width = rendered.canvas.width;
      canvas.height = rendered.canvas.height;
      canvas.style.width = `${rendered.width}px`;
      canvas.style.height = `${rendered.height}px`;
      const context = canvas.getContext("2d");
      if (context) context.drawImage(rendered.canvas, 0, 0);
      textLayer.replaceChildren(rendered.textLayer);
    })().catch(() => {
      // A page that fails to render shows its placeholder number; the rest of
      // the document stays readable rather than the whole view failing (H08).
    });

    return () => {
      cancelled.current = true;
    };
  }, [active, doc, pageNumber, zoom, onSize]);

  const width = Math.round(size.width * (zoom / 100));
  const height = Math.round(size.height * (zoom / 100));

  return (
    <div
      ref={hostRef}
      data-page={pageNumber}
      // `overflow-hidden` is load-bearing: a page that is not active keeps the
      // canvas from its last render, and a zoom change shrinks the box without
      // re-rendering it, so the stale bitmap would spill out and give the
      // whole reader a horizontal scrollbar.
      className="relative mx-auto overflow-hidden bg-surface shadow-sm"
      style={{ width, height }}
    >
      <canvas ref={canvasRef} aria-label={`第 ${String(pageNumber)} 页`} className="block" />
      <div ref={textRef} className="pdf-text-layer" />
      {overlay}
      {highlight && <HighlightBox bbox={highlight} zoom={zoom} />}
      {!active && (
        <span className="absolute inset-0 flex items-center justify-center text-[var(--text-sm)] text-ink-2">
          {pageNumber}
        </span>
      )}
    </div>
  );
}

/** The `--hl` box an anchor highlight draws (02 §4.2). */
function HighlightBox({ bbox, zoom }: { bbox: [number, number, number, number]; zoom: number }) {
  const [x0, y0, x1, y1] = bbox;
  const scale = scaleFor(zoom);
  return (
    <div
      className="pointer-events-none absolute rounded-[3px] bg-[var(--hl)]"
      style={{
        left: x0 * scale,
        top: y0 * scale,
        width: Math.max(4, (x1 - x0) * scale),
        height: Math.max(4, (y1 - y0) * scale),
      }}
    />
  );
}
