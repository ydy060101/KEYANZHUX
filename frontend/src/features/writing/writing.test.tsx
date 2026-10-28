import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DataWorkspace } from "./DataWorkspace";
import { FigureWorkspace } from "./FigureWorkspace";
import { OutlineWorkspace } from "./OutlineWorkspace";
import { TranslateWorkspace } from "./TranslateWorkspace";
import { citationKeys, streamOutline } from "./api";

vi.mock("mermaid", () => ({
  default: {
    initialize: vi.fn(),
    render: vi.fn(() => Promise.resolve({ svg: "<svg xmlns=\"http://www.w3.org/2000/svg\"><text>diagram</text></svg>" })),
  },
}));

vi.mock("./ScriptEditor", () => ({
  ScriptEditor: ({
    value,
    onChange,
    ariaLabel,
  }: {
    value: string;
    onChange: (value: string) => void;
    ariaLabel: string;
  }) => (
    <textarea
      aria-label={ariaLabel}
      value={value}
      onChange={(event) => {
        onChange(event.target.value);
      }}
    />
  ),
}));

vi.mock("./ChartCanvas", () => ({
  ChartCanvas: ({ type, x, y }: { type: string; x: string; y: string[] }) => (
    <div data-testid="data-chart">ECharts {type} {x} {y.join(",")}</div>
  ),
}));

const DRAFT = {
  draft_id: "d1",
  outline: {
    title: "Retrieval with provenance",
    markdown: [
      "# Retrieval with provenance",
      "",
      "## Abstract",
      "",
      "We propose a grounded retriever \\cite{vaswani2017} with $E=mc^2$.",
      "",
      "## Introduction",
      "",
      "The pipeline is auditable \\cite{missing2024}.",
      "",
      "## Related Work",
      "",
      "[待补充]",
    ].join("\n"),
    sections: [
      { heading: "Abstract", markdown: "We propose a grounded retriever \\cite{vaswani2017} with $E=mc^2$." },
      { heading: "Introduction", markdown: "The pipeline is auditable \\cite{missing2024}." },
      { heading: "Related Work", markdown: "[待补充]" },
    ],
    flags: [{ kind: "missing_reference", section: "", text: "框架中有 1 处标记为 [待补充]，需人工补充" }],
  },
  references: [
    {
      key: "vaswani2017",
      title: "Attention Is All You Need",
      authors: ["Ashish Vaswani"],
      year: 2017,
      doi: "10.5555/3295222",
      arxiv_id: "1706.03762",
      source_url: "https://arxiv.org/abs/1706.03762",
      status: "verified",
    },
  ],
  bibtex: "@inproceedings{vaswani2017}",
  flags: [{ kind: "missing_reference", section: "", text: "框架中有 1 处标记为 [待补充]，需人工补充" }],
};

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

function json(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
}

function stubFetch(handler: (url: string, init?: RequestInit) => Response | Promise<Response>): void {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = input instanceof URL ? input.href : typeof input === "string" ? input : input.url;
      return Promise.resolve(handler(url, init));
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("outline workspace", () => {
  it("parses the SSE stages and keeps only references with a title", async () => {
    stubFetch(() =>
      stream(
        sse("stage", { stage: "planning", message: "正在生成框架结构" }),
        sse("stage", { stage: "writing", message: "正在撰写框架正文" }),
        sse("done", { ...DRAFT, references: [...DRAFT.references, { key: "bad", status: "verified" }] }),
      ),
    );
    const events: string[] = [];
    let done: unknown = null;
    await streamOutline({ idea: "grounded retrieval", language: "zh" }, (event) => {
      events.push(event.type);
      if (event.type === "done") done = event.data;
    });
    expect(events).toEqual(["stage", "stage", "done"]);
    const result = done as { references: { key: string }[]; markdown: string };
    expect(result.references).toHaveLength(1);
    expect(result.references[0]?.key).toBe("vaswani2017");
    expect(result.markdown).toContain("\\cite{vaswani2017}");
  });

  it("renders the draft, links citations to the verified reference and shows [待补充]", async () => {
    stubFetch((url) => {
      if (url.includes("/writing/outline")) {
        return stream(sse("done", DRAFT));
      }
      if (url.includes("/writing/references/verify")) {
        return json([{ title: "An invented paper", status: "unverified", source_url: null, doi: null, arxiv_id: null }]);
      }
      if (url.includes("/writing/drafts/d1/bibtex")) return new Response("@inproceedings{vaswani2017}", { status: 200 });
      return json({ error: { code: "not_found", message: "missing" } }, 404);
    });

    render(<OutlineWorkspace />);
    await userEvent.type(screen.getByTestId("writing-idea"), "grounded retrieval");
    await userEvent.click(screen.getByTestId("writing-generate"));

    expect(await screen.findByRole("heading", { level: 1, name: "Retrieval with provenance" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Abstract" })).toBeInTheDocument();
    expect(screen.getByTestId("writing-reference")).toHaveTextContent("Attention Is All You Need");
    expect(screen.getByTestId("writing-reference")).toHaveTextContent("已引用");
    expect(screen.getByTestId("writing-reference-missing")).toHaveTextContent("[待补充]");
    expect(screen.getByTestId("writing-bibtex")).toBeEnabled();
    expect(screen.getByTestId("writing-flag")).toHaveTextContent("[待补充]");

    const chip = screen.getByRole("button", { name: "vaswani2017" });
    await userEvent.click(chip);
    expect(chip.className).toContain("border-primary");

    await userEvent.type(screen.getByTestId("writing-verify-input"), "An invented paper");
    await userEvent.click(screen.getByTestId("writing-verify-button"));
    expect(await screen.findByText("未验证")).toBeInTheDocument();
  });

  it("reports a generation error with a retry", async () => {
    stubFetch(() => stream(sse("error", { error: { code: "llm_unavailable", message: "down" } })));
    render(<OutlineWorkspace />);
    await userEvent.type(screen.getByTestId("writing-idea"), "idea");
    await userEvent.click(screen.getByTestId("writing-generate"));
    expect(await screen.findByText("框架生成失败")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
  });
});

describe("figure workspace", () => {
  const FIGURE = {
    kind: "mermaid",
    script: "graph TD\n  A --> B",
    rendered: null,
    errors: [],
    notes: [],
    renderer: "mermaid",
    attempts: 1,
  };

  it("generates a script, renders Mermaid and exposes the export actions", async () => {
    stubFetch((url) => {
      if (url.includes("/figures/generate")) return json(FIGURE);
      return json({ error: { code: "not_found", message: "missing" } }, 404);
    });
    render(<FigureWorkspace />);
    await userEvent.type(screen.getByTestId("figure-description"), "a two node flow");
    await userEvent.click(screen.getByTestId("figure-generate"));

    expect(await screen.findByLabelText("Mermaid 脚本编辑器")).toHaveValue(FIGURE.script);
    await waitFor(
      () => {
        expect(screen.getByTestId("figure-svg")).toBeInTheDocument();
      },
      { timeout: 2000 },
    );
    expect(screen.getByTestId("figure-export-png")).toBeEnabled();
    expect(screen.getByTestId("figure-run")).toBeEnabled();
  });

  it("shows a readable error and sends the current script to the repair call", async () => {
    let calls = 0;
    stubFetch((url) => {
      if (url.includes("/figures/generate")) {
        calls += 1;
        return json({ ...FIGURE, errors: calls === 1 ? ["line 1: parse error"] : [], renderer: "mermaid" });
      }
      return json({ error: { code: "not_found", message: "missing" } }, 404);
    });
    render(<FigureWorkspace />);
    await userEvent.type(screen.getByTestId("figure-description"), "a broken flow");
    await userEvent.click(screen.getByTestId("figure-generate"));
    const errors = await screen.findByTestId("figure-errors");
    expect(errors).toHaveTextContent("line 1: parse error");
    await userEvent.click(within(errors).getByTestId("figure-repair"));
    await waitFor(() => {
      expect(calls).toBe(2);
    });
    expect(screen.queryByTestId("figure-errors")).not.toBeInTheDocument();
  });
});

describe("data workspace", () => {
  it("uploads a CSV, requests a line chart and shows the editable caption and stats", async () => {
    const seen: { type?: string; x?: string; y?: string[] } = {};
    stubFetch((url, init) => {
      if (url.includes("/data/upload")) {
        return json({
          id: "data-1",
          filename: "accuracy.csv",
          row_count: 6,
          columns: [
            { name: "year", dtype: "int64", missing_rate: 0 },
            { name: "accuracy", dtype: "float64", missing_rate: 0 },
          ],
          preview: [
            { year: 2018, accuracy: 71.2 },
            { year: 2023, accuracy: 89.8 },
          ],
        });
      }
      if (url.includes("/data/data-1/chart")) {
        const body = typeof init?.body === "string" ? (JSON.parse(init.body) as typeof seen) : {};
        seen.type = body.type;
        seen.x = body.x;
        seen.y = body.y;
        return json({
          image_url: "data:image/png;base64,AAAA",
          stats: { min: 71.2, max: 89.8, n: 6 },
          caption: "Accuracy rises from 71.2 to 89.8.",
          caption_zh: "准确率从 71.2 上升到 89.8。",
        });
      }
      return json({ error: { code: "not_found", message: "missing" } }, 404);
    });

    render(<DataWorkspace active />);
    await userEvent.upload(
      screen.getByTestId("data-file"),
      new File(["year,accuracy\n2018,71.2\n2023,89.8"], "accuracy.csv", { type: "text/csv" }),
    );
    expect(await screen.findByTestId("data-meta")).toHaveTextContent("accuracy.csv");
    expect(screen.queryByTestId("data-preview-table")).not.toBeInTheDocument();
    await userEvent.click(screen.getByTestId("data-generate"));

    expect(await screen.findByTestId("data-chart")).toHaveTextContent("ECharts line year accuracy");
    expect(seen).toEqual({ type: "line", x: "year", y: ["accuracy"] });
    const caption = screen.getByTestId("data-caption");
    expect(caption).toHaveValue("Accuracy rises from 71.2 to 89.8.");
    await userEvent.clear(caption);
    await userEvent.type(caption, "Edited caption");
    expect(caption).toHaveValue("Edited caption");
    expect(screen.getByTestId("data-stats")).toHaveTextContent("71.2");
  });
});

describe("academic translation", () => {
  it("posts the Chinese text and renders the English result", async () => {
    stubFetch((url) => {
      if (url.includes("/translate/zh2en")) {
        return json({ text: "We propose a grounded retriever.", direction: "zh2en", cached: false });
      }
      return json({ error: { code: "not_found", message: "missing" } }, 404);
    });
    render(<TranslateWorkspace />);
    await userEvent.type(screen.getByTestId("translate-source"), "我们提出一种可溯源的检索器。");
    await userEvent.click(screen.getByTestId("translate-run"));
    expect(await screen.findByTestId("translate-target")).toHaveTextContent("We propose a grounded retriever.");
    expect(screen.getByTestId("translate-copy")).toBeEnabled();
  });
});

describe("citation keys", () => {
  it("deduplicates keys across citations in document order", () => {
    expect(citationKeys("a \\cite{b,a} b \\cite{a,c}")).toEqual(["b", "a", "c"]);
  });
});
