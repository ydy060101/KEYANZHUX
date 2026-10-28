/** Wire types shared by the writing studio's API modules (T7.5). */

export type FigureKind = "mermaid" | "graphviz" | "tikz" | "matplotlib";
export type ChartKind = "table" | "line" | "bar" | "radar" | "radar3d";

export const FIGURE_LABEL: Record<FigureKind, string> = {
  mermaid: "Mermaid",
  graphviz: "Graphviz",
  tikz: "TikZ",
  matplotlib: "Matplotlib",
};

export const CHART_LABEL: Record<ChartKind, string> = {
  table: "表格",
  line: "折线",
  bar: "柱状",
  radar: "雷达",
  radar3d: "三维雷达",
};

export interface WritingReference {
  key: string;
  title: string;
  authors: string[];
  year: number | null;
  doi: string | null;
  arxivId: string | null;
  sourceUrl: string | null;
  status: "verified" | "unverified";
  similarity: number | null;
}

export interface OutlineSection {
  heading: string;
  markdown: string;
}

export interface OutlineFlag {
  kind: string;
  section: string;
  text: string;
}

export interface OutlineResult {
  draftId: string;
  title: string;
  markdown: string;
  sections: OutlineSection[];
  references: WritingReference[];
  bibtex: string;
  flags: OutlineFlag[];
}

export type OutlineEvent =
  | { type: "stage"; stage: string; message: string; count: number | null }
  | { type: "done"; data: OutlineResult }
  | { type: "error"; message: string };

export interface ReferenceCheck {
  title: string;
  status: "verified" | "unverified";
  sourceUrl: string | null;
  arxivId: string | null;
  doi: string | null;
}

export interface FigureResult {
  kind: FigureKind;
  script: string;
  rendered: string | null;
  errors: string[];
  notes: string[];
  renderer: string;
  attempts: number;
}

export interface DatasetColumn {
  name: string;
  dtype: string;
  missingRate: number;
}

export interface DatasetView {
  id: string;
  filename: string;
  rowCount: number;
  columns: DatasetColumn[];
  preview: Record<string, unknown>[];
}

export interface ChartResult {
  imageUrl: string;
  script: string;
  stats: Record<string, unknown>;
  caption: string;
  captionZh: string;
}

export interface AcademicTranslation {
  text: string;
  cached: boolean;
}
