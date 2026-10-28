import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TranslatePanel } from "./TranslatePanel";
import { translateSelection } from "./translateApi";

const SOURCE = "We use $d_{model}=512$ and $h=8$ heads.";

function sse(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

function stream(...chunks: string[]): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk));
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

const DONE = {
  text: "我们使用 $d_{model}=512$ 和 $h=8$ 个头。",
  direction: "en2zh",
  repaired: false,
  placeholders: 2,
  first_token_ms: 420,
  elapsed_ms: 900,
};

function routeFetch(...chunks: string[]) {
  const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
    const url = input instanceof URL ? input.href : typeof input === "string" ? input : input.url;
    if (url.includes("/translate/selection")) return Promise.resolve(stream(...chunks));
    if (url.includes("/translate/glossary")) {
      return Promise.resolve(
        new Response(JSON.stringify({ version: 0, entries: [], updated_at: null }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
    if (url.includes("/translation")) {
      return Promise.resolve(
        new Response(JSON.stringify({ doc_id: "doc", direction: "en2zh", lang: "zh", blocks: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
    return Promise.resolve(new Response("{}", { status: 200 }));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("selection translation", () => {
  it("posts the text and direction and reports tokens then done", async () => {
    const fetchMock = routeFetch(
      sse("token", { text: "我们使用 " }),
      sse("token", { text: "$d_{model}=512$" }),
      sse("done", DONE),
    );
    const events: string[] = [];
    await translateSelection(SOURCE, "en2zh", (event) => {
      events.push(event.type);
    });
    expect(events).toEqual(["token", "token", "done"]);
    const call = fetchMock.mock.calls[0];
    expect(call?.[0]).toBe("/api/v1/translate/selection");
    const init = call?.[1];
    const body = typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : null;
    expect(body).toEqual({ text: SOURCE, direction: "en2zh" });
  });

  it("streams a selection into the panel and keeps the formulas", async () => {
    routeFetch(
      sse("token", { text: "我们使用 " }),
      sse("token", { text: "$d_{model}=512$" }),
      sse("done", DONE),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <TranslatePanel docId="doc" request={{ text: SOURCE, nonce: 1 }} />
      </QueryClientProvider>,
    );
    const card = await screen.findByTestId("selection-translation");
    await waitFor(() => {
      expect(card).toHaveAttribute("data-translation-status", "done");
    });
    expect(card.textContent).toContain("$d_{model}=512$");
    expect(card.textContent).toContain("首字 420 ms");
    expect(screen.getByTestId("doc-translation-start")).toBeInTheDocument();
  });
});
