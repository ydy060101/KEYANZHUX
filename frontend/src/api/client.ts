import createClient from "openapi-fetch";

import type { paths } from "./schema";

/** Typed client for the contract in openapi.yaml.
 *
 *  The base URL stays same-origin: behind the Vite proxy in development, on
 *  the serving host in production. It is absolute when the page has an http
 *  origin because `openapi-fetch` builds a `Request`, and a `Request` cannot
 *  carry a relative URL outside a browser (unit tests run in Node). A
 *  non-http origin (a packaged file:// build) keeps the relative form. */
const origin =
  typeof window !== "undefined" && window.location.protocol.startsWith("http")
    ? window.location.origin
    : "";

export const api = createClient<paths>({
  baseUrl: `${origin}/api/v1`,
  headers: { "X-User-Id": "default" },
  // Resolve fetch per call: `createClient` otherwise captures the global at
  // import time, which makes the client unreachable from tests that stub it.
  fetch: (input: Request) => globalThis.fetch(input),
});

/** H17: turn the error envelope into something a person can read. */
export interface ApiError {
  code: string;
  message: string;
  detail: Record<string, unknown>;
}

export function toApiError(error: unknown): ApiError {
  if (typeof error === "object" && error !== null && "error" in error) {
    const inner = (error as { error?: unknown }).error;
    if (typeof inner === "object" && inner !== null && "message" in inner) {
      const shaped = inner as { code?: unknown; message?: unknown; detail?: unknown };
      return {
        code: typeof shaped.code === "string" ? shaped.code : "unknown_error",
        message: typeof shaped.message === "string" ? shaped.message : "请求失败",
        detail:
          typeof shaped.detail === "object" && shaped.detail !== null
            ? (shaped.detail as Record<string, unknown>)
            : {},
      };
    }
  }
  return { code: "unknown_error", message: "请求失败，请稍后重试", detail: {} };
}

export function humanMessage(error: ApiError): string {
  switch (error.code) {
    case "not_found":
      return "找不到该资源，它可能已被删除。";
    case "invalid_request":
      return `请求参数有误：${error.message}`;
    case "payload_too_large":
      return "文件超出大小上限，请压缩后重试。";
    case "unsupported_media_type":
      return "只支持 PDF 文件。";
    case "external_service_error":
      return "外部服务暂时不可用，请稍后重试。";
    case "feature_disabled":
      return "该功能当前未启用。";
    case "refused_no_evidence":
      return "未在所选文献中找到依据。";
    default:
      return error.message;
  }
}
