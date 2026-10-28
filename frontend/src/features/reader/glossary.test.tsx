import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GlossaryPanel } from "./GlossaryPanel";
import type { GlossaryEntry } from "./translateApi";

function json(payload: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <GlossaryPanel />
    </QueryClientProvider>,
  );
  return client;
}

function glossaryFetch() {
  let version = 0;
  let entries: GlossaryEntry[] = [];
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = input instanceof URL ? input.href : typeof input === "string" ? input : input.url;
    if (!url.includes("/translate/glossary")) throw new Error(`unexpected request ${url}`);
    if (init?.method === "PUT") {
      const raw = typeof init.body === "string" ? init.body : "{}";
      const body = JSON.parse(raw) as { entries: GlossaryEntry[] };
      entries = body.entries;
      version += 1;
      return json({ version, entries, updated_at: "2026-10-28T00:00:00Z" });
    }
    return json({ version, entries, updated_at: null });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("glossary panel", () => {
  it("starts empty and adds a term at a new version", async () => {
    glossaryFetch();
    renderPanel();

    expect(await screen.findByTestId("glossary-empty")).toBeInTheDocument();
    expect(screen.getByTestId("glossary-version")).toHaveTextContent("v0");

    fireEvent.change(screen.getByLabelText("原文术语"), { target: { value: "attention" } });
    fireEvent.change(screen.getByLabelText("译文术语"), { target: { value: "注意力机制" } });
    fireEvent.click(screen.getByTestId("glossary-add"));

    await waitFor(() => {
      expect(screen.getByTestId("glossary-version")).toHaveTextContent("v1");
    });
    expect(screen.getByText("attention")).toBeInTheDocument();
    expect(screen.getByText("注意力机制")).toBeInTheDocument();
    expect(screen.getByTestId("glossary-notice")).toHaveTextContent("重新翻译");
    expect(screen.getByLabelText("原文术语")).toHaveValue("");
  });

  it("deletes an entry and reports the next version", async () => {
    glossaryFetch();
    renderPanel();

    fireEvent.change(await screen.findByLabelText("原文术语"), { target: { value: "BLEU" } });
    fireEvent.change(screen.getByLabelText("译文术语"), { target: { value: "BLEU 分数" } });
    fireEvent.click(screen.getByTestId("glossary-add"));
    await screen.findByRole("button", { name: "删除术语 BLEU" });

    fireEvent.click(screen.getByRole("button", { name: "删除术语 BLEU" }));

    expect(await screen.findByTestId("glossary-empty")).toBeInTheDocument();
    expect(screen.getByTestId("glossary-version")).toHaveTextContent("v2");
  });

  it("renders the error state with a retry", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(JSON.stringify({ error: { code: "internal_error", message: "读取失败", detail: {} } }), {
            status: 500,
            headers: { "Content-Type": "application/json" },
          }),
        ),
      ),
    );
    renderPanel();

    expect(await screen.findByTestId("glossary-error")).toHaveTextContent("读取失败");
    expect(screen.getByRole("button", { name: /重试/ })).toBeInTheDocument();
  });
});
