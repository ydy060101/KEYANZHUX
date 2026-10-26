import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, humanMessage, toApiError } from "@/api/client";
import type { components } from "@/api/schema";

export type Document = components["schemas"]["Document"];
export type DedupInfo = components["schemas"]["DedupInfo"];
export type UploadResult = components["schemas"]["UploadResult"];

export interface DocumentPage {
  items: Document[];
  total: number;
  page: number;
  page_size: number;
}

export interface LibraryQuery {
  query: string;
  status: string;
  tag: string;
}

export const libraryKeys = {
  all: ["documents"] as const,
  list: (filters: LibraryQuery) => ["documents", "list", filters] as const,
  detail: (id: string) => ["documents", "detail", id] as const,
};

/** A failed request carries the H17 envelope, so callers can show its message. */
export class RequestFailed extends Error {
  readonly code: string;
  readonly detail: Record<string, unknown>;

  constructor(error: unknown) {
    const parsed = toApiError(error);
    super(humanMessage(parsed));
    this.name = "RequestFailed";
    this.code = parsed.code;
    this.detail = parsed.detail;
  }
}

function ensure<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || !result.response.ok) {
    throw new RequestFailed(result.error ?? { error: { message: result.response.statusText } });
  }
  if (result.data === undefined) throw new RequestFailed({ error: { message: "响应缺少数据" } });
  return result.data;
}

export function useDocuments(filters: LibraryQuery) {
  return useQuery({
    queryKey: libraryKeys.list(filters),
    queryFn: async () => {
      const result = await api.GET("/documents", {
        params: {
          query: {
            ...(filters.query ? { query: filters.query } : {}),
            ...(filters.status ? { status: filters.status } : {}),
            ...(filters.tag ? { tag: filters.tag } : {}),
            page: 1,
            page_size: 100,
          },
        },
      });
      return ensure<DocumentPage>(result);
    },
  });
}

export interface UploadOutcome {
  results: UploadResult[];
  /** The first duplicate warning in the batch, if any (01 §8). */
  dedup: { info: DedupInfo; docId: string; filename: string } | null;
}

export function useUploadDocuments() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (files: File[]): Promise<UploadOutcome> => {
      const form = new FormData();
      for (const file of files) form.append("files", file);
      const result = await api.POST("/documents", {
        // openapi-fetch serialises FormData as-is; the generated type expects
        // the JSON shape, so the cast is at this one boundary.
        body: form as unknown as { files: string[] },
      });
      const results = ensure<UploadResult[]>(result);
      const duplicate = results.find((item) => item.dedup);
      return {
        results,
        dedup:
          duplicate && duplicate.dedup
            ? {
                info: duplicate.dedup,
                docId: duplicate.doc_id,
                filename: files[0]?.name ?? "文件",
              }
            : null,
      };
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: libraryKeys.all });
    },
  });
}

export function useResolveDedup() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      docId: string;
      action: "keep_existing" | "replace" | "keep_both";
      targetId: string;
    }) => {
      const result = await api.POST("/documents/{id}/dedup/resolve", {
        params: { path: { id: input.docId } },
        body: { action: input.action, target_id: input.targetId },
      });
      return ensure<Document>(result);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: libraryKeys.all });
    },
  });
}

export function useUpdateDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { id: string; title?: string; tags?: string[] }) => {
      const result = await api.PATCH("/documents/{id}", {
        params: { path: { id: input.id } },
        body: { ...(input.title !== undefined ? { title: input.title } : {}), ...(input.tags ? { tags: input.tags } : {}) },
      });
      return ensure<Document>(result);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: libraryKeys.all });
    },
  });
}

export function useDeleteDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const result = await api.DELETE("/documents/{id}", { params: { path: { id } } });
      if (!result.response.ok) throw new RequestFailed(result.error ?? {});
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: libraryKeys.all });
    },
  });
}

export function useVersionDiff(docId: string | null, otherId: string | null) {
  return useQuery({
    queryKey: ["documents", "diff", docId, otherId],
    enabled: Boolean(docId && otherId),
    queryFn: async () => {
      const result = await api.GET("/documents/{id}/versions/diff", {
        params: { path: { id: docId ?? "" }, query: { other: otherId ?? "" } },
      });
      return ensure<components["schemas"]["VersionDiff"]>(result);
    },
  });
}
