import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GraphView } from "./api";
import { createGraph, fetchGraph, toGraph } from "./api";
import { GraphPage } from "./GraphPage";

// The canvas needs a real bitmap; the page's data flow is what is under test.
vi.mock("./CytoscapeGraph", () => ({
  CytoscapeGraph: ({ graph, onSelect }: { graph: GraphView; onSelect: (id: string | null) => void }) => (
    <div data-testid="graph-canvas">
      {graph.nodes.map((node) => (
        <button
          key={node.id}
          type="button"
          onClick={() => {
            onSelect(node.id);
          }}
        >
          {node.title}
        </button>
      ))}
    </div>
  ),
}));

const GRAPH = {
  id: "g1",
  nodes: [
    {
      id: "a",
      title: "Attention Is All You Need",
      year: 2017,
      role: "cornerstone",
      pagerank: 0.7,
      in_degree: 2,
      out_degree: 0,
      betweenness: 0.5,
      reason: "PageRank 前 20%（0.700），入度 2",
    },
    {
      id: "b",
      title: "BERT",
      year: 2018,
      role: "peripheral",
      pagerank: 0.3,
      in_degree: 0,
      out_degree: 1,
      betweenness: 0,
      reason: "入度 0、出度 1：只引用他人",
    },
  ],
  edges: [
    { source: "b", target: "a", method: "title", confidence: 1, contexts: ["BERT cites attention"] },
    { source: "b", target: "ghost", method: "doi", confidence: 1, contexts: [] },
  ],
  metrics: { node_count: 2, edge_count: 1, unmatched_references: 5, isolated: [] },
};

const DOCS = {
  items: [
    { id: "a", sha256: "a".repeat(64), title: "Attention Is All You Need", status: "ready", page_count: 15, stats: { references: 40 } },
    { id: "b", sha256: "b".repeat(64), title: "BERT", status: "ready", page_count: 16, stats: { references: 30 } },
    { id: "c", sha256: "c".repeat(64), title: "Still parsing", status: "parsing", page_count: 3 },
  ],
  total: 3,
  page: 1,
  page_size: 100,
};

function json(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
}

function routeFetch(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = input instanceof URL ? input.href : typeof input === "string" ? input : input.url;
      if (url.includes("/documents")) return Promise.resolve(json(DOCS));
      if (url.includes("/graphs/g1")) return Promise.resolve(json(GRAPH));
      if (url.includes("/graphs")) return Promise.resolve(json({ id: "job-1", kind: "graph", status: "queued" }, 202));
      return Promise.resolve(json({ error: { code: "not_found", message: "missing" } }, 404));
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Routes>
          <Route path="/graph/:graphId?" element={<GraphPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("citation graph", () => {
  it("normalizes the wire graph and drops edges to unknown nodes", async () => {
    routeFetch();
    const parsed = toGraph(GRAPH);
    expect(parsed?.nodes[0]).toMatchObject({ id: "a", role: "cornerstone", inDegree: 2, betweenness: 0.5 });
    expect(parsed?.edges).toHaveLength(1);
    expect(parsed?.edges[0]?.source).toBe("b");

    const graph = await fetchGraph("g1");
    expect(graph.metrics["unmatched_references"]).toBe(5);

    const job = await createGraph(["a", "b"]);
    expect(job.id).toBe("job-1");
    const call = vi.mocked(fetch).mock.calls.find(
      ([, init]) => typeof init?.body === "string" && init.body.includes("doc_ids"),
    );
    expect(call?.[1]?.body).toBe(JSON.stringify({ doc_ids: ["a", "b"] }));
  });

  it("answers a missing graph with the error state, not an empty canvas", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(json({ error: { code: "not_found", message: "missing" } }, 404))),
    );
    renderAt("/graph/missing");
    expect(await screen.findByText("图谱加载失败")).toBeInTheDocument();
  });

  it("shows the node detail and rankings from the real graph", async () => {
    routeFetch();
    renderAt("/graph/g1");
    expect(await screen.findByTestId("graph-canvas")).toBeInTheDocument();
    expect(screen.getByTestId("graph-summary").textContent).toContain("2 节点 · 1 边");

    await userEvent.click(within(screen.getByTestId("graph-canvas")).getByRole("button", { name: "BERT" }));
    const detail = await screen.findByTestId("graph-detail");
    expect(detail.textContent).toContain("BERT");
    expect(detail.textContent).toContain("入度");
    expect(detail.textContent).toContain("0.300");

    const row = screen.getByTestId("graph-metrics-row");
    expect(row.textContent).toContain("Attention Is All You Need");
    await userEvent.click(row);
    expect(await screen.findByText("判定依据：PageRank 前 20%（0.700），入度 2")).toBeInTheDocument();
  });

  it("keeps the build button disabled until two parsed documents are chosen", async () => {
    routeFetch();
    renderAt("/graph");
    expect(await screen.findByText("2 篇可建图 · 已选 0")).toBeInTheDocument();
    const build = screen.getByTestId("graph-build");
    expect(build).toBeDisabled();
    expect(screen.getByLabelText("Still parsing")).toBeDisabled();

    const [first, second] = screen.getAllByTestId("graph-doc");
    await userEvent.click(first as HTMLElement);
    expect(build).toBeDisabled();
    await userEvent.click(second as HTMLElement);
    await waitFor(() => {
      expect(build).toBeEnabled();
    });
  });
});
