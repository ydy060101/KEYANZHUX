import type { PDFDocumentProxy } from "pdfjs-dist";
import { useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";

import { useReader } from "./readerStore";

export type Bbox = [number, number, number, number];

/** A four-number bbox, or null when the array is the wrong shape. */
export function asBbox(value: number[] | undefined | null): Bbox | null {
  if (!value || value.length !== 4) return null;
  const [x0, y0, x1, y1] = value;
  if (x0 === undefined || y0 === undefined || x1 === undefined || y1 === undefined) return null;
  if (![x0, y0, x1, y1].every((item) => Number.isFinite(item))) return null;
  return [x0, y0, x1, y1];
}

/** A `bbox=a,b,c,d` query value, or null when it is not four finite numbers. */
export function parseBbox(value: string | null): Bbox | null {
  if (!value) return null;
  return asBbox(value.split(",").map(Number));
}

/**
 * Land the full reader on an anchor passed in the URL.
 *
 * `/reader/:docId?page=7&bbox=…` is how a QA chip opens a paper it is not
 * already showing. The query is applied once per document and search string,
 * so the reader's own scrolling is not undone on every re-render.
 */
export function useAnchorQuery(doc: PDFDocumentProxy | null, docId: string): void {
  const [params] = useSearchParams();
  const jump = useReader((state) => state.jump);
  const applied = useRef("");
  const search = params.toString();

  useEffect(() => {
    if (!doc) return;
    const key = `${docId}?${search}`;
    if (applied.current === key) return;
    applied.current = key;
    const page = Number(params.get("page") ?? "");
    if (!Number.isFinite(page) || page < 1) return;
    const target = Math.min(doc.numPages, Math.max(1, Math.floor(page)));
    const bbox = parseBbox(params.get("bbox"));
    if (bbox) jump({ page: target, bbox, highlight: true });
    else jump({ page: target });
  }, [doc, docId, jump, params, search]);
}
