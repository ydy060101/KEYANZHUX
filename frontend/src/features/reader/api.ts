import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { components } from "@/api/schema";

import { ensure } from "@/features/library/api";

export type Block = components["schemas"]["Block"];
export type OutlineItem = components["schemas"]["OutlineItem"];
export type Reference = components["schemas"]["Reference"];
export type Asset = components["schemas"]["Asset"];
export type Citation = components["schemas"]["Citation"];
export type DocMeta = components["schemas"]["DocMeta"];
export type Document = components["schemas"]["Document"];

/** The structure call as the reader consumes it: every list present. */
export interface Structure {
  meta: DocMeta;
  outline: OutlineItem[];
  assets: Asset[];
  references: Reference[];
}

/** What the reader assumes of a reference: the fields it renders. */
export interface Ref {
  id: string;
  index: number;
  raw: string;
  title: string | null;
  authors: string[];
  year: number | null;
  block_id: string;
  page: number | null;
  bbox: number[];
  worth_score?: number;
  worth_reasons?: string[];
}

export interface Cite {
  id: string;
  marker: string;
  ref_ids: string[];
  block_id: string;
  page: number | null;
  bbox: number[];
  method?: "link_annotation" | "regex";
}

export function asReference(reference: Reference): Ref {
  return {
    id: reference.id,
    index: reference.index,
    raw: reference.raw,
    title: reference.title ?? null,
    authors: reference.authors ?? [],
    year: reference.year ?? null,
    block_id: reference.block_id ?? "",
    page: reference.page ?? null,
    bbox: reference.bbox ?? [],
    ...(reference.worth_score !== undefined ? { worth_score: reference.worth_score } : {}),
    ...(reference.worth_reasons ? { worth_reasons: reference.worth_reasons } : {}),
  };
}

export function asCitation(citation: Citation): Cite {
  return {
    id: citation.id,
    marker: citation.marker,
    ref_ids: citation.ref_ids ?? [],
    block_id: citation.block_id,
    page: citation.page ?? null,
    bbox: citation.bbox ?? [],
    ...(citation.method ? { method: citation.method } : {}),
  };
}

export const readerKeys = {
  document: (id: string) => ["reader", id, "document"] as const,
  structure: (id: string) => ["reader", id, "structure"] as const,
  page: (id: string, page: number) => ["reader", id, "page", page] as const,
  citations: (id: string) => ["reader", id, "citations"] as const,
};

/** Everything the reader needs before it can draw its first page. */
export function useReaderDocument(docId: string | null) {
  return useQuery({
    queryKey: readerKeys.document(docId ?? "none"),
    enabled: Boolean(docId),
    queryFn: async () => {
      const result = await api.GET("/documents/{id}", { params: { path: { id: docId ?? "" } } });
      return ensure<Document>(result);
    },
  });
}

export function useStructure(docId: string | null) {
  return useQuery({
    queryKey: readerKeys.structure(docId ?? "none"),
    enabled: Boolean(docId),
    queryFn: async (): Promise<Structure> => {
      const result = await api.GET("/documents/{id}/structure", { params: { path: { id: docId ?? "" } } });
      const body = ensure<{
        meta?: DocMeta;
        outline?: OutlineItem[];
        assets?: Asset[];
        references?: Reference[];
      }>(result);
      return {
        meta: body.meta ?? {},
        outline: body.outline ?? [],
        assets: body.assets ?? [],
        references: body.references ?? [],
      };
    },
    // The structure of a parsed document does not change while it is open.
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * One page's blocks (T2.6).
 *
 * Pages are fetched as they scroll into view rather than all at once: a
 * 541-page book has 10 748 blocks, and shipping them on open would make the
 * first paint wait for text the reader has not reached.
 */
export function usePageBlocks(docId: string | null, page: number | null) {
  return useQuery({
    queryKey: readerKeys.page(docId ?? "none", page ?? 0),
    enabled: Boolean(docId && page && page > 0),
    queryFn: async () => {
      const result = await api.GET("/documents/{id}/pages/{n}/blocks", {
        params: { path: { id: docId ?? "", n: page ?? 1 } },
      });
      return ensure<Block[]>(result);
    },
    staleTime: 10 * 60 * 1000,
  });
}

/** Citation markers with the reference ids and bboxes they point at (T2.3). */
export function useCitations(docId: string | null) {
  return useQuery({
    queryKey: readerKeys.citations(docId ?? "none"),
    enabled: Boolean(docId),
    queryFn: async (): Promise<Cite[]> => {
      const result = await api.GET("/documents/{id}/citations", { params: { path: { id: docId ?? "" } } });
      return ensure<Citation[]>(result).map(asCitation);
    },
    staleTime: 10 * 60 * 1000,
  });
}

/** The PDF bytes, streamed by the browser with Range support (T1.2). */
export function fileUrl(docId: string): string {
  return `/api/v1/documents/${encodeURIComponent(docId)}/file`;
}
