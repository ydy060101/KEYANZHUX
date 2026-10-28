import { create } from "zustand";

/** A place in the document the reader can jump to (02 §4.2). */
export interface Target {
  page: number;
  blockId?: string;
  /** The bbox to highlight; QA anchors carry it, outline jumps do not. */
  bbox?: number[];
  /** Highlight the block's bbox after scrolling to it. */
  highlight?: boolean;
}

interface ReaderState {
  page: number;
  zoom: number;
  fitWidth: boolean;
  activeSectionId: string | null;
  /** What the reader last scrolled to, so the outline can follow. */
  pending: Target | null;
  /** A reference whose entry should flash, set by "返回引用处". */
  flashRefId: string | null;
  setPage: (page: number) => void;
  setZoom: (zoom: number) => void;
  toggleFitWidth: () => void;
  setActiveSection: (id: string | null) => void;
  jump: (target: Target) => void;
  consumePending: () => Target | null;
  flashReference: (refId: string | null) => void;
}

const MIN_ZOOM = 50;
const MAX_ZOOM = 300;

/** The zoom range the toolbar offers; also used when fitting to width. */
export function clampZoom(zoom: number): number {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom));
}

export const useReader = create<ReaderState>((set, get) => ({
  page: 1,
  zoom: 100,
  fitWidth: true,
  activeSectionId: null,
  pending: null,
  flashRefId: null,
  setPage: (page) => set({ page: Math.max(1, page) }),
  setZoom: (zoom) => set({ zoom: clampZoom(zoom), fitWidth: false }),
  toggleFitWidth: () => set((s) => ({ fitWidth: !s.fitWidth })),
  setActiveSection: (id) => set({ activeSectionId: id }),
  jump: (target) => set({ pending: target, page: target.page }),
  consumePending: () => {
    const pending = get().pending;
    if (pending) set({ pending: null });
    return pending;
  },
  flashReference: (refId) => set({ flashRefId: refId }),
}));
