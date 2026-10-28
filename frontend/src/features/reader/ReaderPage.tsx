import { BookOpen } from "lucide-react";
import type { PDFDocumentProxy } from "pdfjs-dist";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { EmptyState, ErrorState, Skeleton } from "@/design/States";
import type { QaAnchor } from "@/features/qa/api";
import { asReference, fileUrl, useCitations, useReaderDocument, useStructure } from "./api";
import { asBbox, useAnchorQuery } from "./anchorQuery";
import { CitationCard } from "./CitationCard";
import { CitationOverlay } from "./CitationOverlay";
import { LeftRail, type LeftTab } from "./LeftRail";
import { PageView, type PageSize } from "./PageView";
import { loadPdf, pageSize as measurePage } from "./pdf";
import { useReader, clampZoom } from "./readerStore";
import { Toolbar } from "./ReaderToolbar";
import { RightRail, type RightTab } from "./RightRail";
import { SelectionToolbar } from "./SelectionToolbar";
import { HIGHLIGHT_MS, useCitationLinks } from "./useCitationLinks";

/** How many pages either side of the viewport keep a rendered bitmap. */
const WINDOW = 2;
/** The middle rail's horizontal padding (`px-6`), which the page must not fill. */
const FIT_PADDING = 48;

export function ReaderPage() {
  const { docId = "" } = useParams();
  const navigate = useNavigate();
  const documentQuery = useReaderDocument(docId);
  const structureQuery = useStructure(docId);
  const citationsQuery = useCitations(docId);

  const page = useReader((s) => s.page);
  const zoom = useReader((s) => s.zoom);
  const setZoom = useReader((s) => s.setZoom);
  const setPage = useReader((s) => s.setPage);
  const jump = useReader((s) => s.jump);
  const setActiveSection = useReader((s) => s.setActiveSection);
  const activeSection = useReader((s) => s.activeSectionId);
  const consumePending = useReader((s) => s.consumePending);
  const pending = useReader((s) => s.pending);
  const flashRefId = useReader((s) => s.flashRefId);

  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [sizes, setSizes] = useState<Record<number, PageSize>>({});
  const [visible, setVisible] = useState<Set<number>>(() => new Set([1, 2, 3]));
  const [highlight, setHighlight] = useState<{ page: number; bbox: [number, number, number, number] } | null>(null);
  const [leftTab, setLeftTab] = useState<LeftTab>("toc");
  const [rightTab, setRightTab] = useState<RightTab>("structure");

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const nodes = useRef(new Map<number, HTMLDivElement>());
  const pendingScroll = useRef<number | null>(null);

  const pageCount = documentQuery.data?.page_count ?? 0;

  // ---- load the PDF -----------------------------------------------------
  useEffect(() => {
    if (!docId) return;
    // A ref, not a closure variable: TypeScript narrows a value the cleanup
    // reassigns and then flags the guard as dead code, and the guard is what
    // stops a slow load from writing into a page that is gone.
    const cancelled = { current: false };
    const isCancelled = () => cancelled.current;
    setDoc(null);
    setLoadError(null);
    void loadPdf(docId)
      .then(async (loaded) => {
        if (isCancelled()) return;
        setDoc(loaded);
        // The page box must be right before the first paint, or the scroll
        // position the reader restores lands on the wrong page.
        const first = await measurePage(loaded, 1);
        if (isCancelled()) return;
        // Fit the width in the same commit as the first measured page: an
        // anchor jump is applied as soon as page 1's size is known, and a
        // zoom change one commit later would move every page under it.
        const host = scrollRef.current;
        if (useReader.getState().fitWidth && host) {
          const available = host.clientWidth - FIT_PADDING;
          if (available > 0) {
            useReader.setState({ zoom: clampZoom(Math.floor((available / first.width) * 100)) });
          }
        }
        setSizes({ 1: first });
      })
      .catch((error: unknown) => {
        if (isCancelled()) return;
        setLoadError(error instanceof Error ? error.message : "PDF 加载失败");
      });
    return () => {
      cancelled.current = true;
    };
  }, [docId]);

  useAnchorQuery(doc, docId);

  const register = useCallback((pageNumber: number, node: HTMLDivElement | null) => {
    if (node) nodes.current.set(pageNumber, node);
    else nodes.current.delete(pageNumber);
  }, []);

  // 适应宽度 (02 §4.2): the page is as wide as the middle rail allows. The
  // scale is computed from the page's own width in PDF units, so a document
  // set on A4 and one set on Letter both fill the rail exactly. The rail's
  // width is measured rather than assumed, because it changes with the
  // window and with the two side rails.
  const fitWidth = useReader((s) => s.fitWidth);
  const toggleFitWidth = useReader((s) => s.toggleFitWidth);
  useEffect(() => {
    const host = scrollRef.current;
    if (!host || !fitWidth) return;
    const first = sizes[1];
    if (!first) return;
    const measure = () => {
      const available = host.clientWidth - FIT_PADDING;
      if (available <= 0) return;
      // `setZoom` would clear fitWidth, so the store's setter is not used here.
      useReader.setState({ zoom: clampZoom(Math.floor((available / first.width) * 100)) });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(host);
    return () => {
      observer.disconnect();
    };
  }, [fitWidth, sizes]);

  const onSize = useCallback((pageNumber: number, size: PageSize) => {
    setSizes((prev) => (prev[pageNumber] ? prev : { ...prev, [pageNumber]: size }));
  }, []);

  const onActive = useCallback(
    (pageNumber: number) => {
      setPage(pageNumber);
      setVisible((prev) => {
        const next = new Set<number>();
        for (let n = Math.max(1, pageNumber - WINDOW); n <= Math.min(pageCount || pageNumber + WINDOW, pageNumber + WINDOW); n += 1) {
          next.add(n);
        }
        if (next.size === prev.size && [...next].every((n) => prev.has(n))) return prev;
        return next;
      });
      const heading = structureQuery.data?.outline.filter((item) => item.page <= pageNumber).at(-1);
      setActiveSection(heading?.id ?? null);
    },
    [pageCount, setActiveSection, setPage, structureQuery.data?.outline],
  );

  // ---- scrolling to a target --------------------------------------------
  // An instant scroll is used for programmatic jumps: the page boxes are
  // sized from page 1 until a page is measured, and a smooth animation would
  // keep moving while those sizes settle, landing the reader pages away from
  // the target on a long book.
  const scrollToPage = useCallback((target: number, smooth = true) => {
    const node = nodes.current.get(target);
    if (node) {
      node.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" });
      return;
    }
    pendingScroll.current = target;
    setPage(target);
  }, [setPage]);

  useEffect(() => {
    if (!pendingScroll.current) return;
    const node = nodes.current.get(pendingScroll.current);
    if (!node) return;
    node.scrollIntoView({ block: "start" });
    pendingScroll.current = null;
  }, [sizes]);

  // A jump requested by the outline, the structure panel or an anchor. It is
  // applied once page 1's true size is known: before that, every unmeasured
  // page is a Letter-sized placeholder and the target's offset is wrong.
  useEffect(() => {
    if (!pending || !sizes[1]) return;
    consumePending();
    scrollToPage(pending.page, false);
    if (!pending.highlight) return;
    const direct = pending.bbox ? asBbox(pending.bbox) : null;
    const block =
      direct === null && pending.blockId
        ? citationsQuery.data?.find((c) => c.block_id === pending.blockId)
        : undefined;
    const box = direct ?? asBbox(block?.bbox);
    if (!box) return;
    setHighlight({ page: pending.page, bbox: box });
    window.setTimeout(() => {
      setHighlight(null);
    }, HIGHLIGHT_MS);
  }, [pending, sizes, consumePending, scrollToPage, citationsQuery.data]);

  // ---- citation interaction ---------------------------------------------
  const openStructure = useCallback(() => {
    setRightTab("structure");
  }, []);

  // A QA anchor for this paper jumps in place; another paper's anchor opens
  // the full reader on the page and bbox the query names.
  const openAnchor = useCallback(
    (anchor: QaAnchor) => {
      if (anchor.doc_id === docId) {
        jump({ page: anchor.page, blockId: anchor.block_id, bbox: anchor.bbox, highlight: true });
        return;
      }
      const params = new URLSearchParams({ page: String(anchor.page) });
      if (anchor.bbox.length === 4) params.set("bbox", anchor.bbox.join(","));
      void navigate(`/reader/${encodeURIComponent(anchor.doc_id)}?${params.toString()}`);
    },
    [docId, jump, navigate],
  );
  const references = useMemo(
    () => (structureQuery.data?.references ?? []).map(asReference),
    [structureQuery.data?.references],
  );
  const links = useCitationLinks(references, citationsQuery.data ?? [], openStructure);

  // ---- render ------------------------------------------------------------
  if (!docId) {
    return (
      <EmptyState
        title="还没有打开文献"
        description="从资料库选择一篇文献，或先上传一份 PDF。"
        icon={<BookOpen className="size-6" aria-hidden />}
        action={
          <button
            type="button"
            onClick={() => {
              navigate("/library");
            }}
            className="rounded-control bg-primary px-4 py-2 text-[var(--text-sm)] font-medium text-white"
          >
            去资料库
          </button>
        }
      />
    );
  }

  if (documentQuery.isPending) {
    return <ReaderSkeleton />;
  }

  if (documentQuery.isError) {
    return (
      <ErrorState
        message="无法打开这篇文献"
        detail={documentQuery.error.message}
        onRetry={() => {
          void documentQuery.refetch();
        }}
      />
    );
  }

  const total = pageCount || 1;

  return (
    <div className="flex h-full min-h-0">
      <LeftRail
        tab={leftTab}
        onTab={setLeftTab}
        outline={structureQuery.data?.outline ?? []}
        activeId={activeSection}
        onPick={(item) => {
          setActiveSection(item.id);
          jump({ page: item.page, blockId: item.block_id, highlight: true });
        }}
        total={total}
        page={page}
        onPickPage={scrollToPage}
      />

      <section className="flex min-w-0 flex-1 flex-col bg-surface-2">
        <Toolbar
          page={page}
          total={total}
          zoom={zoom}
          fitWidth={fitWidth}
          onZoom={(next) => {
            setZoom(next);
          }}
          onFitWidth={() => {
            toggleFitWidth();
          }}
          onPage={(next) => {
            scrollToPage(Math.min(total, Math.max(1, next)));
          }}
          fileHref={fileUrl(docId)}
        />

        {loadError ? (
          <ErrorState message="PDF 渲染失败" detail={loadError} />
        ) : (
          <div ref={scrollRef} data-reader-scroll className="app-scroll flex-1 px-6 py-6">
            {doc ? (
              <div className="mx-auto flex w-fit flex-col gap-4">
                {Array.from({ length: total }, (_, index) => index + 1).map((pageNumber) => (
                  <PageView
                    key={pageNumber}
                    doc={doc}
                    pageNumber={pageNumber}
                    size={sizes[pageNumber] ?? sizes[1] ?? { width: 612, height: 792 }}
                    active={visible.has(pageNumber)}
                    zoom={zoom}
                    highlight={highlight?.page === pageNumber ? highlight.bbox : null}
                    onSize={onSize}
                    onActive={onActive}
                    register={register}
                    overlay={
                      <CitationOverlay
                        citations={links.citationsByPage.get(pageNumber) ?? []}
                        zoom={zoom}
                        onHover={(x, y, marker, citation) => {
                          links.openCard(x, y, marker, citation, pageNumber);
                        }}
                        onLeave={links.scheduleHoverClose}
                        onOpen={(citation) => {
                          const reference = links.referenceById.get(citation.ref_ids?.[0] ?? "");
                          if (reference) links.openReference(reference);
                          links.setHover(null);
                        }}
                      />
                    }
                  />
                ))}
              </div>
            ) : (
              <PageSkeleton />
            )}
          </div>
        )}

        {links.hover && (
          <div
            className="fixed z-20 -translate-x-1/2"
            style={{ left: links.hover.x, top: links.hover.y }}
            onMouseEnter={links.cancelHoverClose}
            onMouseLeave={links.scheduleHoverClose}
          >
            <CitationCard
              marker={links.hover.marker}
              references={links.hoverRefs}
              onOpen={(reference) => {
                void navigate(`/discover?q=${encodeURIComponent(reference.title ?? reference.raw)}`);
              }}
              onJump={links.openReference}
            />
          </div>
        )}
      </section>

      <RightRail
        tab={rightTab}
        onTab={setRightTab}
        meta={structureQuery.data?.meta}
        assets={structureQuery.data?.assets ?? []}
        references={references}
        flashRefId={flashRefId}
        lastCitation={links.lastCitation}
        onJumpPage={(target) => {
          scrollToPage(target);
        }}
        onJumpReference={links.openReference}
        onBackToCitation={links.backToCitation}
        docId={docId}
        docTitle={documentQuery.data.title}
        onOpenAnchor={openAnchor}
      />

      <SelectionToolbar
        onTranslate={() => {
          setRightTab("translate");
        }}
        onAsk={() => {
          setRightTab("qa");
        }}
        onHighlight={() => {
          /* highlighting a selection is T4.1; the toolbar is shared with it */
        }}
      />
    </div>
  );
}

function ReaderSkeleton() {
  return (
    <div className="flex h-full min-h-0">
      <div className="w-[248px] shrink-0 border-r border-border p-3">
        <Skeleton className="h-6 w-full" />
        <div className="mt-3 space-y-2">
          {Array.from({ length: 8 }, (_, i) => (
            <Skeleton key={i} className="h-4 w-full" />
          ))}
        </div>
      </div>
      <div className="flex flex-1 items-center justify-center">
        <PageSkeleton />
      </div>
      <div className="w-[340px] shrink-0 border-l border-border p-3">
        <Skeleton className="h-6 w-full" />
      </div>
    </div>
  );
}

function PageSkeleton() {
  return <Skeleton className="h-[70vh] w-[520px] max-w-full" />;
}
