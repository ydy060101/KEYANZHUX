import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { type Citation, type Ref } from "./api";
import type { CitationTarget } from "./CitationCard";
import { useReader } from "./readerStore";
import { referencesFor } from "./references";

/** How long an anchor highlight stays at full strength before fading (02 §4.2). */
export const HIGHLIGHT_MS = 3000;

interface Hover {
  x: number;
  y: number;
  marker: string;
  refIds: string[];
}

/**
 * The reader's citation plumbing: the hover card, and the two halves of the
 * bidirectional jump (marker → bibliography entry, entry → marker).
 *
 * Kept out of the page component because the pointer handling is subtle — the
 * card sits below the marker, so closing on `mouseleave` alone unmounts it
 * before the pointer can reach 跳转 — and because the page was over the
 * 400-line file limit in H14.
 */
export function useCitationLinks(
  references: Ref[],
  citations: Citation[],
  onOpenStructure: () => void,
) {
  const jump = useReader((s) => s.jump);
  const flashReference = useReader((s) => s.flashReference);

  const [hover, setHover] = useState<Hover | null>(null);
  const [lastCitation, setLastCitation] = useState<CitationTarget | null>(null);

  const referenceById = useMemo(() => {
    const map = new Map<string, Ref>();
    for (const reference of references) map.set(reference.id, reference);
    return map;
  }, [references]);

  const citationsByPage = useMemo(() => {
    const map = new Map<number, Citation[]>();
    for (const citation of citations) {
      const pageNo = citation.page ?? 1;
      const list = map.get(pageNo) ?? [];
      list.push(citation);
      map.set(pageNo, list);
    }
    return map;
  }, [citations]);

  // The card sits just below the marker, so the pointer has to cross a gap to
  // reach it. Closing on `mouseleave` alone would unmount the card before the
  // pointer arrived, making 跳转 impossible to click; the close is deferred
  // and cancelled when the pointer lands on the card.
  const hoverTimer = useRef<number | null>(null);
  const cancelHoverClose = useCallback(() => {
    if (hoverTimer.current !== null) {
      window.clearTimeout(hoverTimer.current);
      hoverTimer.current = null;
    }
  }, []);
  const scheduleHoverClose = useCallback(() => {
    cancelHoverClose();
    hoverTimer.current = window.setTimeout(() => {
      setHover(null);
      hoverTimer.current = null;
    }, 160);
  }, [cancelHoverClose]);
  useEffect(() => cancelHoverClose, [cancelHoverClose]);

  /** A marker was hovered: show its card and remember where it is. */
  const openCard = useCallback(
    (x: number, y: number, marker: string, citation: Citation, fallbackPage: number) => {
      cancelHoverClose();
      setHover({ x, y, marker, refIds: citation.ref_ids ?? [] });
      // Remember where the marker is, so the bibliography entry's
      // "返回引用处" can come back to it.
      setLastCitation({ page: citation.page ?? fallbackPage, blockId: citation.block_id });
    },
    [cancelHoverClose],
  );

  /** Scroll to a bibliography entry and flash it. */
  const openReference = useCallback(
    (reference: Ref) => {
      onOpenStructure();
      flashReference(reference.id);
      window.setTimeout(() => {
        flashReference(null);
      }, HIGHLIGHT_MS);
      jump({ page: reference.page ?? 1, blockId: reference.block_id, highlight: true });
      window.setTimeout(() => {
        document.querySelector(`[data-ref-id="${reference.id}"]`)?.scrollIntoView({ block: "center" });
      }, 60);
    },
    [flashReference, jump, onOpenStructure],
  );

  /** "返回引用处": back from the entry to the marker that named it. */
  const backToCitation = useCallback(() => {
    if (!lastCitation) return;
    jump({ page: lastCitation.page, blockId: lastCitation.blockId, highlight: true });
  }, [jump, lastCitation]);

  const hoverRefs = useMemo(
    () => (hover ? referencesFor(hover.refIds, references) : []),
    [hover, references],
  );

  return {
    hover,
    hoverRefs,
    setHover,
    lastCitation,
    citationsByPage,
    referenceById,
    cancelHoverClose,
    scheduleHoverClose,
    openCard,
    openReference,
    backToCitation,
  };
}
