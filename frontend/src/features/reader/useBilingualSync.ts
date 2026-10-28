import { useCallback, useEffect, useRef, useState, type MutableRefObject, type RefObject } from "react";

import { bboxTop, offsetWithin, pickAtLine, type Positioned } from "./bilingual";
import { scaleFor } from "./pdf";
import type { TranslationBlock } from "./translateApi";

/** How long a programmatic scroll may keep a column from driving the other. */
const LOCK_MS = 240;

type Blocks = readonly TranslationBlock[];
type Rows = Map<string, HTMLDivElement>;

function usePdfPositions(
  pdfScrollRef: RefObject<HTMLDivElement | null>,
  pageNodes: RefObject<Map<number, HTMLDivElement>>,
  blocksRef: MutableRefObject<Blocks>,
  zoomRef: MutableRefObject<number>,
): () => Positioned[] {
  return useCallback((): Positioned[] => {
    const host = pdfScrollRef.current;
    if (!host) return [];
    const scale = scaleFor(zoomRef.current);
    const found: Positioned[] = [];
    for (const block of blocksRef.current) {
      if (block.bbox.length !== 4) continue;
      const page = pageNodes.current?.get(block.page);
      if (!page) continue;
      const top = bboxTop(host, page, block.bbox, scale);
      const y0 = block.bbox[1] ?? 0;
      const y1 = block.bbox[3] ?? y0;
      found.push({ id: block.block_id, top, bottom: top + Math.max(8, (y1 - y0) * scale) });
    }
    return found;
  }, [blocksRef, pageNodes, pdfScrollRef, zoomRef]);
}

function useRowPositions(
  paneRef: RefObject<HTMLDivElement | null>,
  rows: MutableRefObject<Rows>,
): () => Positioned[] {
  return useCallback((): Positioned[] => {
    const pane = paneRef.current;
    if (!pane) return [];
    const found: Positioned[] = [];
    for (const [id, row] of rows.current) {
      const top = offsetWithin(pane, row);
      found.push({ id, top, bottom: top + row.offsetHeight });
    }
    return found;
  }, [paneRef, rows]);
}

function useRevealBlock(
  pdfScrollRef: RefObject<HTMLDivElement | null>,
  pageNodes: RefObject<Map<number, HTMLDivElement>>,
  blocksRef: MutableRefObject<Blocks>,
  zoomRef: MutableRefObject<number>,
  currentRef: MutableRefObject<string | null>,
  setCurrent: (id: string) => void,
  ignorePdf: MutableRefObject<number>,
): (id: string) => void {
  return useCallback(
    (id: string) => {
      const block = blocksRef.current.find((item) => item.block_id === id);
      const host = pdfScrollRef.current;
      const page = block ? pageNodes.current?.get(block.page) : undefined;
      if (!block || !host || !page || block.bbox.length !== 4) return;
      const top = bboxTop(host, page, block.bbox, scaleFor(zoomRef.current));
      ignorePdf.current = performance.now() + LOCK_MS;
      host.scrollTop = Math.max(0, top - 8);
      if (currentRef.current !== id) setCurrent(id);
    },
    [blocksRef, currentRef, ignorePdf, pageNodes, pdfScrollRef, setCurrent, zoomRef],
  );
}

function useSyncFromPdf(
  pdfScrollRef: RefObject<HTMLDivElement | null>,
  paneRef: RefObject<HTMLDivElement | null>,
  blocksRef: MutableRefObject<Blocks>,
  rows: MutableRefObject<Rows>,
  pdfPositions: () => Positioned[],
  currentRef: MutableRefObject<string | null>,
  setCurrent: (id: string) => void,
  ignorePdf: MutableRefObject<number>,
  ignorePane: MutableRefObject<number>,
): () => void {
  const frame = useRef(0);

  const sync = useCallback(() => {
    const host = pdfScrollRef.current;
    const pane = paneRef.current;
    if (!host || !pane || blocksRef.current.length === 0) return;
    if (performance.now() < ignorePdf.current) return;
    const line = host.scrollTop + Math.min(180, Math.max(48, host.clientHeight * 0.22));
    const hit = pickAtLine(pdfPositions(), line);
    if (!hit) return;
    if (hit.id !== currentRef.current) setCurrent(hit.id);
    const row = rows.current.get(hit.id);
    if (!row) return;
    const box = row.getBoundingClientRect();
    const view = pane.getBoundingClientRect();
    if (box.bottom > view.top + 4 && box.top < view.bottom - 4) return;
    ignorePane.current = performance.now() + LOCK_MS;
    pane.scrollTop = Math.max(0, offsetWithin(pane, row) - 8);
  }, [blocksRef, currentRef, ignorePane, ignorePdf, paneRef, pdfPositions, pdfScrollRef, rows, setCurrent]);

  useEffect(
    () => () => {
      if (frame.current) cancelAnimationFrame(frame.current);
    },
    [],
  );

  return useCallback(() => {
    if (frame.current) return;
    frame.current = requestAnimationFrame(() => {
      frame.current = 0;
      sync();
    });
  }, [sync]);
}

function useSyncFromPane(
  paneRef: RefObject<HTMLDivElement | null>,
  rowPositions: () => Positioned[],
  currentRef: MutableRefObject<string | null>,
  revealBlock: (id: string) => void,
  ignorePane: MutableRefObject<number>,
): () => void {
  const frame = useRef(0);

  const sync = useCallback(() => {
    const pane = paneRef.current;
    if (!pane || performance.now() < ignorePane.current) return;
    const line = pane.scrollTop + Math.min(120, Math.max(36, pane.clientHeight * 0.18));
    const hit = pickAtLine(rowPositions(), line);
    if (!hit || hit.id === currentRef.current) return;
    revealBlock(hit.id);
  }, [currentRef, ignorePane, paneRef, revealBlock, rowPositions]);

  useEffect(
    () => () => {
      if (frame.current) cancelAnimationFrame(frame.current);
    },
    [],
  );

  return useCallback(() => {
    if (frame.current) return;
    frame.current = requestAnimationFrame(() => {
      frame.current = 0;
      sync();
    });
  }, [sync]);
}

function usePdfListener(
  pdfScrollRef: RefObject<HTMLDivElement | null>,
  onScroll: () => void,
): void {
  useEffect(() => {
    const host = pdfScrollRef.current;
    if (!host) return;
    host.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      host.removeEventListener("scroll", onScroll);
    };
  }, [onScroll, pdfScrollRef]);
}

function useAlignment(
  blocks: Blocks,
  pdfScrollRef: RefObject<HTMLDivElement | null>,
  paneRef: RefObject<HTMLDivElement | null>,
  pdfPositions: () => Positioned[],
  rows: MutableRefObject<Rows>,
  setCurrent: (id: string | null) => void,
  ignorePane: MutableRefObject<number>,
  zoom: number,
): void {
  useEffect(() => {
    if (blocks.length === 0) {
      setCurrent(null);
      return;
    }
    let inner = 0;
    const outer = requestAnimationFrame(() => {
      inner = requestAnimationFrame(() => {
        const host = pdfScrollRef.current;
        const pane = paneRef.current;
        if (!host || !pane) return;
        const line = host.scrollTop + Math.min(180, Math.max(48, host.clientHeight * 0.22));
        const hit = pickAtLine(pdfPositions(), line);
        const row = hit ? rows.current.get(hit.id) : undefined;
        if (!hit || !row) return;
        setCurrent(hit.id);
        ignorePane.current = performance.now() + LOCK_MS;
        pane.scrollTop = Math.max(0, offsetWithin(pane, row) - 8);
      });
    });
    return () => {
      cancelAnimationFrame(outer);
      if (inner) cancelAnimationFrame(inner);
    };
  }, [blocks, ignorePane, paneRef, pdfPositions, pdfScrollRef, rows, setCurrent, zoom]);
}

export interface LinkedScroll {
  current: string | null;
  revealBlock: (id: string) => void;
  onPaneScroll: () => void;
}

/** Block-identity scroll linkage between the PDF and translation columns. */
export function useLinkedScroll({
  pdfScrollRef,
  pageNodes,
  paneRef,
  rows,
  blocks,
  zoom,
}: {
  pdfScrollRef: RefObject<HTMLDivElement | null>;
  pageNodes: RefObject<Map<number, HTMLDivElement>>;
  paneRef: RefObject<HTMLDivElement | null>;
  rows: MutableRefObject<Rows>;
  blocks: Blocks;
  zoom: number;
}): LinkedScroll {
  const [current, setCurrentState] = useState<string | null>(null);
  const currentRef = useRef<string | null>(null);
  const blocksRef = useRef<Blocks>(blocks);
  blocksRef.current = blocks;
  const zoomRef = useRef(zoom);
  zoomRef.current = zoom;
  const ignorePane = useRef(0);
  const ignorePdf = useRef(0);

  const setCurrent = useCallback((id: string | null) => {
    currentRef.current = id;
    setCurrentState(id);
  }, []);

  const pdfPositions = usePdfPositions(pdfScrollRef, pageNodes, blocksRef, zoomRef);
  const rowPositions = useRowPositions(paneRef, rows);
  const revealBlock = useRevealBlock(
    pdfScrollRef,
    pageNodes,
    blocksRef,
    zoomRef,
    currentRef,
    setCurrent,
    ignorePdf,
  );
  const onPdfScroll = useSyncFromPdf(
    pdfScrollRef,
    paneRef,
    blocksRef,
    rows,
    pdfPositions,
    currentRef,
    setCurrent,
    ignorePdf,
    ignorePane,
  );
  const onPaneScroll = useSyncFromPane(paneRef, rowPositions, currentRef, revealBlock, ignorePane);
  usePdfListener(pdfScrollRef, onPdfScroll);
  useAlignment(blocks, pdfScrollRef, paneRef, pdfPositions, rows, setCurrent, ignorePane, zoom);

  return { current, revealBlock, onPaneScroll };
}
