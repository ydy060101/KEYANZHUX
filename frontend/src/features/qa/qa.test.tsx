import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Document } from "@/features/library/api";
import { CompareAnswer } from "./CompareTable";
import { QaChat } from "./QaChat";
import { ScopePicker } from "./ScopePicker";
import {
  askQuestion,
  NOT_FOUND,
  splitFrames,
  type CompareTable,
  type QaAnchor,
  type QaEvent,
  type QaScope,
} from "./api";
import { useQaHistory } from "./history";
import { compareToMarkdown } from "./markdown";

const ANCHOR: QaAnchor = {
  doc_id: "doc",
  block_id: "b2_3",
  page: 2,
  bbox: [10, 10, 120, 30],
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

const DONE = {
  answer: "The model uses 8 GPUs [1].",
  citations: [{ marker: "[1]", anchor: ANCHOR, quote: "We trained on 8 GPUs." }],
  refused: false,
  flags: [],
};

function mockFetch(...chunks: string[]) {
  const fetchMock = vi.fn(() => Promise.resolve(stream(...chunks)));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function askInChat() {
  const onOpen = vi.fn();
  render(
    <QaChat
      scope={{ type: "all", doc_ids: [] }}
      mode="qa"
      docTitles={{ doc: "A Paper" }}
      onOpenAnchor={onOpen}
    />,
  );
  await userEvent.type(screen.getByLabelText("提问"), "How many GPUs?");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));
  await waitFor(() => {
    expect(screen.getByTestId("qa-turn")).not.toHaveAttribute("data-qa-status", "streaming");
  });
  return onOpen;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

beforeEach(() => {
  useQaHistory.setState({ sessions: [] });
  localStorage.clear();
});

describe("SSE transport", () => {
  it("keeps an incomplete frame for the next chunk and ignores keepalives", () => {
    const first = splitFrames(": keepalive\n\nevent: token\ndata: {\"text\":\"Hel");
    expect(first.frames).toHaveLength(0);
    expect(first.rest).toContain("event: token");

    const second = splitFrames(`${first.rest}lo"}\n\n`);
    expect(second.frames).toHaveLength(1);
    expect(second.frames[0]?.event).toBe("token");
    expect(JSON.parse(second.frames[0]?.data ?? "")).toEqual({ text: "Hello" });
  });

  it("parses token, anchor and done into typed events", async () => {
    mockFetch(
      sse("token", { text: DONE.answer }),
      sse("anchor", { marker: "[1]", anchor: ANCHOR, quote: "We trained on 8 GPUs." }),
      sse("done", DONE),
    );
    const events: QaEvent[] = [];
    await askQuestion(
      { question: "q", scope: { type: "all", doc_ids: [] }, mode: "qa" },
      (event) => {
        events.push(event);
      },
    );
    expect(events.map((event) => event.type)).toEqual(["token", "anchor", "done"]);
    const done = events[2];
    expect(done?.type).toBe("done");
    if (done?.type === "done") {
      expect(done.data.citations[0]?.anchor.page).toBe(2);
      expect(done.data.refused).toBe(false);
    }
  });
});

describe("chat", () => {
  it("renders the verified answer with a clickable inline anchor chip", async () => {
    mockFetch(
      sse("token", { text: "The model uses 8 GPUs " }),
      sse("anchor", { marker: "[1]", anchor: ANCHOR, quote: "We trained on 8 GPUs." }),
      sse("token", { text: "[1]." }),
      sse("done", DONE),
    );
    const onOpen = await askInChat();

    expect(screen.getByText(/8 GPUs/)).toBeInTheDocument();
    const chip = screen.getByRole("button", { name: /引用 \[1\]，第 2 页/ });
    await userEvent.click(chip);
    expect(onOpen).toHaveBeenCalledWith(ANCHOR);
  });

  it("shows the refusal card when the backend refuses", async () => {
    mockFetch(
      sse("token", { text: "未在所选文献中找到依据。" }),
      sse("done", {
        answer: "未在所选文献中找到依据。",
        citations: [],
        refused: true,
        flags: [{ kind: "weak_support", text: "最高重排分低于阈值" }],
      }),
    );
    await askInChat();
    expect(screen.getByTestId("qa-refusal")).toBeInTheDocument();
    expect(screen.getByText(/未在所选文献中找到依据/)).toBeInTheDocument();
    expect(screen.getByText(/最高重排分低于阈值/)).toBeInTheDocument();
  });

  it("shows an error card when the stream reports one", async () => {
    mockFetch(
      sse("error", { error: { code: "llm_unavailable", message: "语言模型暂时不可用，请稍后重试", detail: {} } }),
    );
    await askInChat();
    expect(screen.getByTestId("qa-error")).toBeInTheDocument();
    expect(screen.getByText("语言模型暂时不可用，请稍后重试")).toBeInTheDocument();
  });

  it("disables sending when the scope has no document", () => {
    render(
      <QaChat
        scope={{ type: "doc", doc_ids: [] }}
        mode="qa"
        docTitles={{}}
        onOpenAnchor={vi.fn()}
      />,
    );
    expect(screen.getByText("请先选择文献")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
  });
});

describe("compare table", () => {
  const table: CompareTable = {
    dimensions: ["number of layers"],
    table: [
      {
        dimension: "number of layers",
        cells: {
          a: { text: "N = 6", citations: [{ ...ANCHOR, doc_id: "a" }] },
          b: { text: NOT_FOUND, citations: [] },
        },
      },
    ],
    summary: "Compared 2 papers on 1 dimensions: 1/2 cells have source evidence.",
    flags: [],
  };

  it("renders every cell and anchors only the grounded one", () => {
    render(
      <CompareAnswer table={table} documents={{ a: "Paper A", b: "Paper B" }} onOpenAnchor={vi.fn()} />,
    );
    expect(screen.getByText("N = 6")).toBeInTheDocument();
    expect(screen.getByText(NOT_FOUND)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /第 2 页原文/ })).toBeInTheDocument();
  });

  it("exports the same cells, pages and sources as Markdown", () => {
    const markdown = compareToMarkdown(table, { a: "Paper A", b: "Paper B" });
    expect(markdown).toContain("| 维度 | Paper A | Paper B |");
    expect(markdown).toContain("N = 6（p.2）");
    expect(markdown).toContain(NOT_FOUND);
    expect(markdown).toContain("- Paper A：第 2 页");
  });
});

const DOCUMENTS = [
  { id: "a", title: "Paper A", status: "ready" },
  { id: "b", title: "Paper B", status: "ready" },
] as unknown as Document[];

function Picker() {
  const [scope, setScope] = useState<QaScope>({ type: "set", doc_ids: [] });
  return (
    <ScopePicker
      scope={scope}
      onChange={setScope}
      documents={DOCUMENTS}
      loading={false}
      error={null}
      onRetry={vi.fn()}
      max={2}
    />
  );
}

describe("scope picker", () => {
  it("adds documents to a checked set and reflects the count", async () => {
    render(<Picker />);
    await userEvent.click(screen.getByRole("button", { name: "选择文献" }));
    await userEvent.click(screen.getByRole("button", { name: /Paper A/ }));
    expect(screen.getByText("已选 1 篇")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Paper B/ }));
    expect(screen.getByText("已选 2 篇")).toBeInTheDocument();
  });

  it("filters the document list by title", async () => {
    render(<Picker />);
    await userEvent.click(screen.getByRole("button", { name: "选择文献" }));
    await userEvent.type(screen.getByLabelText("搜索文献"), "B");
    expect(screen.queryByRole("button", { name: /Paper A/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Paper B/ })).toBeInTheDocument();
  });
});

describe("history", () => {
  it("stores and removes a completed session", () => {
    const turn = {
      id: "t1",
      question: "How many GPUs?",
      answer: DONE.answer,
      citations: DONE.citations,
      refused: false,
      flags: [],
      status: "done" as const,
      createdAt: "2026-10-28T00:00:00Z",
    };
    useQaHistory.getState().upsert({
      id: "s1",
      title: "How many GPUs?",
      createdAt: "2026-10-28T00:00:00Z",
      updatedAt: "2026-10-28T00:00:00Z",
      scope: { type: "all", doc_ids: [] },
      mode: "qa",
      turns: [turn],
    });
    expect(useQaHistory.getState().sessions).toHaveLength(1);
    useQaHistory.getState().remove("s1");
    expect(useQaHistory.getState().sessions).toHaveLength(0);
  });
});
