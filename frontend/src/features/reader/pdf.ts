import * as pdfjs from "pdfjs-dist";
import type { PDFDocumentProxy, PDFPageProxy } from "pdfjs-dist";

import { fileUrl } from "./api";

/**
 * The pdf.js document, loaded once per open (T2.6).
 *
 * The worker is loaded through Vite's `new URL(..., import.meta.url)` form so
 * the worker comes from the same installed pdfjs-dist as the library: a
 * version mismatch between the two is the most common way pdf.js fails at
 * runtime, and it fails as a silent blank page.
 */
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

const cache = new Map<string, Promise<PDFDocumentProxy>>();

export function loadPdf(docId: string): Promise<PDFDocumentProxy> {
  let pending = cache.get(docId);
  if (!pending) {
    pending = pdfjs.getDocument({ url: fileUrl(docId), withCredentials: false }).promise;
    cache.set(docId, pending);
    pending.catch(() => {
      // A failed load must not poison the cache: a retry must re-fetch.
      cache.delete(docId);
    });
  }
  return pending;
}

export function forgetPdf(docId: string): void {
  const pending = cache.get(docId);
  cache.delete(docId);
  void pending?.then((doc) => doc.destroy()).catch(() => undefined);
}

/** The page box as the reader lays it out at 100 % zoom. */
export async function pageSize(doc: PDFDocumentProxy, pageNumber: number): Promise<{ width: number; height: number }> {
  const page = await doc.getPage(pageNumber);
  const viewport = page.getViewport({ scale: BASE_SCALE });
  return { width: viewport.width, height: viewport.height };
}

/**
 * PDF units → CSS pixels at `zoom` percent.
 *
 * One function for every coordinate the reader places: the page box, the
 * anchor highlight and the citation hit boxes all use it, so a bbox from the
 * API lands on the glyphs it describes at every zoom level.
 */
export function scaleFor(zoom: number): number {
  return BASE_SCALE * (zoom / 100);
}

export interface RenderedPage {
  /** CSS pixels at the current zoom. */
  width: number;
  height: number;
  canvas: HTMLCanvasElement;
  textLayer: HTMLDivElement;
}

const BASE_SCALE = 1.35; // ≈ 130 dpi at 100 %, comfortable for a page on screen

/**
 * Render one page at `zoom` percent, with a selectable text layer.
 *
 * The text layer is what makes selection, the floating toolbar and the
 * citation hover cards possible, so it is built here rather than in the
 * component: canvas and text must use the same viewport, or the selectable
 * text drifts away from the glyphs it belongs to.
 */
export async function renderPage(
  doc: PDFDocumentProxy,
  pageNumber: number,
  zoom: number,
): Promise<RenderedPage> {
  const page = await doc.getPage(pageNumber);
  return renderWith(page, zoom);
}

async function renderWith(page: PDFPageProxy, zoom: number): Promise<RenderedPage> {
  const viewport = page.getViewport({ scale: scaleFor(zoom) });
  const canvas = document.createElement("canvas");
  // Cap the pixel ratio: a 3× phone canvas of an A4 page is 20 MB of bitmap
  // for detail the eye cannot resolve, and the reader keeps several alive.
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.floor(viewport.width * ratio);
  canvas.height = Math.floor(viewport.height * ratio);
  canvas.style.width = `${viewport.width}px`;
  canvas.style.height = `${viewport.height}px`;
  const context = canvas.getContext("2d");
  if (context) {
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    await page.render({ canvasContext: context, viewport }).promise;
  }

  const textLayer = document.createElement("div");
  textLayer.className = "pdf-text-layer-inner";
  const textContent = await page.getTextContent();
  const layer = new pdfjs.TextLayer({ textContentSource: textContent, container: textLayer, viewport });
  await layer.render();
  return { width: viewport.width, height: viewport.height, canvas, textLayer };
}
