import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DiscoverPage } from "./DiscoverPage";
import { importPaper, searchPapers } from "./api";

const HITS = [
  {
    title: "Attention Is All You Need",
    source: "arxiv",
    ext_id: "1706.03762",
    authors: ["Ashish Vaswani"],
    year: 2017,
    abstract: "The Transformer.",
    arxiv_id: "1706.03762",
    doi: null,
    pdf_url: "https://arxiv.org/pdf/1706.03762",
    github_url: null,
    stars: null,
    in_library: true,
  },
  { title: "no ext id", source: "arxiv" },
];

function json(payload: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

function routeFetch(searchHeaders: Record<string, string> = {}) {
  const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
    const url = input instanceof URL ? input.href : typeof input === "string" ? input : input.url;
    if (url.includes("/recommendations")) return Promise.resolve(json([]));
    if (url.includes("/discover/search")) return Promise.resolve(json(HITS, 200, searchHeaders));
    if (url.includes("/discover/fetch")) {
      return Promise.resolve(json({ id: "job-1", kind: "import", status: "queued" }, 202));
    }
    return Promise.resolve(json({}));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("discovery", () => {
  it("keeps the import id and drops hits the backend could not complete", async () => {
    routeFetch();
    const result = await searchPapers("attention");
    expect(result.hits).toHaveLength(1);
    expect(result.hits[0]).toMatchObject({ ext_id: "1706.03762", in_library: true });
    expect(result.degraded).toEqual([]);
    const job = await importPaper("arxiv", "1706.03762");
    expect(job.id).toBe("job-1");
  });

  it("reports the sources that failed through the Warning header", async () => {
    routeFetch({ Warning: '199 research-agent "semanticscholar crossref unavailable"' });
    const result = await searchPapers("attention");
    expect(result.degraded).toEqual(["semanticscholar", "crossref"]);
  });

  it("renders live search hits with the library badge", async () => {
    routeFetch();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <DiscoverPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await userEvent.click(screen.getByRole("tab", { name: "搜索下载" }));
    await userEvent.type(screen.getByTestId("discover-query"), "attention");
    await userEvent.click(screen.getByTestId("discover-search"));
    await waitFor(() => {
      expect(screen.getByTestId("discover-count").textContent).toContain("1 条结果");
    });
    const card = screen.getByTestId("discover-hit");
    expect(card.textContent).toContain("Attention Is All You Need");
    expect(card.textContent).toContain("已在库中");
  });

  it("says the library is empty instead of showing sample recommendations", async () => {
    routeFetch();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <DiscoverPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByText("还没有可推荐的文献")).toBeInTheDocument();
  });
});
