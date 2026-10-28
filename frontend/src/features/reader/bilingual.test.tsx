import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState, useMemo, type RefObject } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { bboxTop, offsetWithin, pickAtLine } from "./bilingual";
import { BilingualPane } from "./BilingualPane";
import type { Direction } from "./translateApi";

vi.mock("./pdf", () => ({ scaleFor: (zoom: number) => 1.35 * (zoom / 100) }));

const BLOCKS = [
  {
    block_id: "b1",
    page: 1,
    type: "paragraph",
    bbox: [72, 100, 540, 160],
    original: "Attention is all you need.",
    translation: "只需要注意力。",
  },
  {
    block_id: "b2",
    page: 1,
    type: "heading",
    bbox: [72, 180, 540, 200],
    original: "Results",
    translation: "结果",
  },
];

function json(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function routeTranslation(blocks = BLOCKS) {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = input instanceof URL ? input.href : typeof input === "string" ? input : input.url;
    if (url.includes("direction=zh2en")) {
      return Promise.resolve(
        json({ doc_id: "doc", direction: "zh2en", lang: "en", blocks: [] }),
      );
    }
    return Promise.resolve(
      json({ doc_id: "doc", direction: "en2zh", lang: "zh", blocks }),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function fakeBox(top: number): DOMRect {
  return { top } as unknown as DOMRect;
}

function scrollHost(top = 0): HTMLDivElement {
  const node = document.createElement("div");
  Object.defineProperty(node, "getBoundingClientRect", { value: () => fakeBox(top) });
  Object.defineProperty(node, "scrollTop", { value: 0, writable: true });
  return node;
}

function PaneHarness({
  pdf,
  pageNodes,
  onClose,
  onOpen,
}: {
  pdf: RefObject<HTMLDivElement | null>;
  pageNodes: Map<number, HTMLDivElement>;
  onClose: () => void;
  onOpen: () => void;
}) {
  const [direction, setDirection] = useState<Direction>("en2zh");
  const nodes = useMemo(() => ({ current: pageNodes }), [pageNodes]);
  return (
    <BilingualPane
      docId="doc"
      direction={direction}
      onDirection={setDirection}
      pdfScrollRef={pdf}
      pageNodes={nodes}
      zoom={100}
      onClose={onClose}
      onOpenTranslateTab={onOpen}
    />
  );
}

function renderPane(options: { pageNodes?: Map<number, HTMLDivElement>; onClose?: () => void; onOpen?: () => void } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const host = scrollHost();
  const pdf = { current: host } as RefObject<HTMLDivElement | null>;
  const view = render(
    <QueryClientProvider client={client}>
      <PaneHarness
        pdf={pdf}
        pageNodes={options.pageNodes ?? new Map()}
        onClose={options.onClose ?? (() => undefined)}
        onOpen={options.onOpen ?? (() => undefined)}
      />
    </QueryClientProvider>,
  );
  return { ...view, host };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("block picker", () => {
  it("picks the nearest item at or above the reading line", () => {
    const items = [
      { id: "a", top: 0, bottom: 40 },
      { id: "b", top: 100, bottom: 140 },
      { id: "c", top: 300, bottom: 340 },
    ];
    expect(pickAtLine(items, 150)?.id).toBe("b");
    expect(pickAtLine(items, 100)?.id).toBe("b");
    expect(pickAtLine(items, 500)?.id).toBe("c");
  });

  it("falls back to the first item when the line is above everything", () => {
    expect(pickAtLine([{ id: "a", top: 40, bottom: 80 }], 0)?.id).toBe("a");
    expect(pickAtLine([], 0)).toBeNull();
  });

  it("does not assume reading order and prefers the later item on a tie", () => {
    const items = [
      { id: "late", top: 200, bottom: 240 },
      { id: "early", top: 0, bottom: 40 },
      { id: "middle", top: 100, bottom: 140 },
    ];
    expect(pickAtLine(items, 150)?.id).toBe("middle");
    expect(
      pickAtLine(
        [
          { id: "first", top: 50, bottom: 90 },
          { id: "second", top: 50, bottom: 90 },
        ],
        60,
      )?.id,
    ).toBe("second");
  });

  it("maps a bbox into the PDF scroll container's coordinates", () => {
    const host = scrollHost(50);
    host.scrollTop = 30;
    const page = scrollHost(200);
    expect(offsetWithin(host, page)).toBe(180);
    expect(bboxTop(host, page, [0, 10, 0, 20], 2)).toBe(200);
  });
});

describe("bilingual pane", () => {
  it("renders block-aligned translations with page labels", async () => {
    routeTranslation();
    renderPane();
    expect(await screen.findByText("只需要注意力。")).toBeInTheDocument();
    expect(screen.getByText("结果")).toBeInTheDocument();
    expect(screen.getAllByText("第 1 页")).toHaveLength(2);
    expect(screen.getByTestId("bilingual-pane")).toHaveAttribute("data-direction", "en2zh");
  });

  it("changes the translation font size independently", async () => {
    routeTranslation();
    renderPane();
    const row = await screen.findByText("只需要注意力。");
    expect(row).toHaveStyle({ fontSize: "15px" });
    fireEvent.click(screen.getByLabelText("增大译文字号"));
    expect(row).toHaveStyle({ fontSize: "16px" });
    fireEvent.click(screen.getByLabelText("减小译文字号"));
    expect(row).toHaveStyle({ fontSize: "15px" });
    expect(screen.getByTestId("bilingual-font-size")).toHaveTextContent("15");
  });

  it("switches direction and offers the translation tab when that direction is empty", async () => {
    routeTranslation();
    const onOpen = vi.fn();
    renderPane({ onOpen });
    await screen.findByText("只需要注意力。");
    fireEvent.click(screen.getByRole("button", { name: "中 → 英" }));
    expect(await screen.findByTestId("bilingual-empty")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "前往翻译" }));
    expect(onOpen).toHaveBeenCalledOnce();
  });

  it("clicking a row reveals the same block in the PDF", async () => {
    routeTranslation();
    const pageNodes = new Map<number, HTMLDivElement>([[1, scrollHost(100)]]);
    const onClose = vi.fn();
    const { host } = renderPane({ pageNodes, onClose });
    await screen.findByText("结果");
    fireEvent.click(screen.getByText("结果"));
    // block b2 starts at y=180 on a page 100 px down, at 135 % scale.
    await waitFor(() => {
      expect(host.scrollTop).toBe(335);
    });
    expect(screen.getByTestId("bilingual-pane")).toHaveAttribute("data-current-block", "b2");
    fireEvent.click(screen.getByLabelText("退出对照模式"));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
