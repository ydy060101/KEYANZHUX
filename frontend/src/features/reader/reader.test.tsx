import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { asCitation, asReference } from "@/features/reader/api";
import { CitationCard, ReferenceList, WorthMeter } from "@/features/reader/CitationCard";
import { OutlinePanel } from "@/features/reader/OutlinePanel";
import { useReader } from "@/features/reader/readerStore";
import { referencesFor } from "@/features/reader/references";

const OUTLINE = [
  { id: "h1", level: 1, title: "1 Introduction", page: 1, block_id: "b1_1" },
  { id: "h2", level: 2, title: "1.1 Motivation", page: 2, block_id: "b2_1" },
  { id: "h3", level: 1, title: "2 Method", page: 5, block_id: "b5_1" },
];

describe("outline panel", () => {
  it("jumps to the page of the heading that was clicked", async () => {
    const onPick = vi.fn();
    render(<OutlinePanel items={OUTLINE} activeId="h1" onPick={onPick} />);
    await userEvent.click(screen.getByRole("button", { name: /2 Method/ }));
    expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ id: "h3", page: 5 }));
  });

  it("filters a long book's headings by title", async () => {
    render(<OutlinePanel items={OUTLINE} activeId={null} onPick={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("过滤标题"), "motiv");
    expect(screen.getByRole("button", { name: /1\.1 Motivation/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /2 Method/ })).not.toBeInTheDocument();
    expect(screen.getByText("1 条")).toBeInTheDocument();
  });

  it("collapses a branch so its children are hidden", async () => {
    render(<OutlinePanel items={OUTLINE} activeId={null} onPick={vi.fn()} />);
    expect(screen.getByRole("button", { name: /1\.1 Motivation/ })).toBeInTheDocument();
    const collapses = screen.getAllByRole("button", { name: "折叠" });
    expect(collapses.length).toBeGreaterThan(0);
    await userEvent.click(collapses[0] as HTMLElement);
    expect(screen.queryByRole("button", { name: /1\.1 Motivation/ })).not.toBeInTheDocument();
  });

  it("says so when the PDF has no headings", () => {
    render(<OutlinePanel items={[]} activeId={null} onPick={vi.fn()} />);
    expect(screen.getByText("这份 PDF 没有可用的标题结构。")).toBeInTheDocument();
  });
});

const REFERENCE = asReference({
  id: "r11",
  index: 11,
  raw: "Vaswani et al. Attention Is All You Need. 2017.",
  title: "Attention Is All You Need",
  authors: ["Ashish Vaswani", "Noam Shazeer"],
  year: 2017,
  block_id: "b9_4",
  page: 9,
  bbox: [0, 0, 10, 10],
  worth_score: 82,
});

describe("citation cards", () => {
  it("shows the reference a marker points at, with its worth score", () => {
    render(<CitationCard marker="11" references={[REFERENCE]} onOpen={vi.fn()} onJump={vi.fn()} />);
    expect(screen.getByText("Attention Is All You Need")).toBeInTheDocument();
    expect(screen.getByText(/2017/)).toBeInTheDocument();
    expect(screen.getByTitle("含金量 82/100")).toBeInTheDocument();
  });

  it("says a marker has no entry rather than inventing one (H02)", () => {
    render(<CitationCard marker="99" references={[]} onOpen={vi.fn()} onJump={vi.fn()} />);
    expect(screen.getByText(/没有对应的参考文献条目/)).toBeInTheDocument();
  });

  it("labels a missing score as unrated instead of showing zero", () => {
    render(<WorthMeter score={undefined} />);
    expect(screen.getByText("含金量未评分")).toBeInTheDocument();
  });

  it("jumps from a marker to the bibliography entry", async () => {
    const onJump = vi.fn();
    render(<CitationCard marker="11" references={[REFERENCE]} onOpen={vi.fn()} onJump={onJump} />);
    await userEvent.click(screen.getByRole("button", { name: "跳转" }));
    expect(onJump).toHaveBeenCalledWith(REFERENCE);
  });

  it("offers 返回引用处 on a bibliography entry once a marker was visited", async () => {
    const onBackTo = vi.fn();
    render(
      <ReferenceList
        references={[REFERENCE]}
        flashId={null}
        onJump={vi.fn()}
        onBackTo={onBackTo}
        lastCitation={{ page: 4, blockId: "b4_2" }}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /返回引用处/ }));
    expect(onBackTo).toHaveBeenCalledWith(REFERENCE);
  });

  it("hides 返回引用处 when no marker has been visited", () => {
    render(
      <ReferenceList references={[REFERENCE]} flashId={null} onJump={vi.fn()} onBackTo={vi.fn()} lastCitation={null} />,
    );
    expect(screen.queryByRole("button", { name: /返回引用处/ })).not.toBeInTheDocument();
  });
});

describe("reader store", () => {
  it("clamps zoom to the range the toolbar offers", () => {
    useReader.getState().setZoom(5000);
    expect(useReader.getState().zoom).toBe(300);
    useReader.getState().setZoom(-10);
    expect(useReader.getState().zoom).toBe(50);
  });

  it("hands a jump target over exactly once", () => {
    useReader.getState().jump({ page: 12, blockId: "b12_1", highlight: true });
    expect(useReader.getState().consumePending()).toEqual({ page: 12, blockId: "b12_1", highlight: true });
    expect(useReader.getState().consumePending()).toBeNull();
  });
});

describe("citation normalisation", () => {
  it("fills the optional arrays the API may omit", () => {
    const citation = asCitation({ id: "c1", marker: "[3]", block_id: "b2_1" });
    expect(citation.ref_ids).toEqual([]);
    expect(citation.bbox).toEqual([]);
    expect(citation.page).toBeNull();
  });
});

describe("resolving a marker to its entries", () => {
  const ALPHA = asReference({
    id: "r-mccd13",
    index: 1,
    raw: "Mikolov et al. Efficient estimation. 2013.",
    title: "Efficient estimation of word representations",
    authors: ["Tomas Mikolov"],
    year: 2013,
    block_id: "b9_1",
    page: 9,
    bbox: [0, 0, 10, 10],
  });

  it("follows the ref_ids the parser resolved, not the marker's text", () => {
    // "[MCCD13]" is not a number, so deriving entry 13 from the marker found
    // nothing and the card said "no entry" for every GPT-3 citation.
    expect(referencesFor(["r-mccd13"], [REFERENCE, ALPHA])).toEqual([ALPHA]);
  });

  it("keeps a multi-entry marker's entries in the order they were resolved", () => {
    expect(referencesFor(["r-mccd13", "r11"], [REFERENCE, ALPHA])).toEqual([ALPHA, REFERENCE]);
  });

  it("returns nothing rather than a guess when the ids resolve to no entry (H02)", () => {
    expect(referencesFor(["r-missing"], [REFERENCE, ALPHA])).toEqual([]);
  });
});
