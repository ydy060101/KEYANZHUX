import type { components } from "@/api/schema";

/** Fixture data for the T0.5 prototype. Enabled only when VITE_USE_MOCK=1
 *  (H16) so no mock can leak into a production build. */

export type Document = components["schemas"]["Document"];
export type Reference = components["schemas"]["Reference"];
export type OutlineItem = components["schemas"]["OutlineItem"];
export type Block = components["schemas"]["Block"];

export const USE_MOCK = import.meta.env.VITE_USE_MOCK === "1";

export const mockDocuments: Document[] = [
  {
    id: "11111111-1111-4111-8111-111111111111",
    sha256: "a".repeat(64),
    arxiv_id: "1706.03762",
    version: "v7",
    title: "Attention Is All You Need",
    status: "ready",
    source_kind: "vector",
    page_count: 15,
    tags: ["Transformer", "NLP"],
    created_at: "2026-10-20T09:12:00Z",
    stats: { blocks: 412, figures: 5, tables: 4, formulas: 11, references: 40 },
  },
  {
    id: "22222222-2222-4222-8222-222222222222",
    sha256: "b".repeat(64),
    arxiv_id: "1810.04805",
    version: "v2",
    title: "BERT: Pre-training of Deep Bidirectional Transformers",
    status: "ready",
    source_kind: "vector",
    page_count: 16,
    tags: ["BERT", "NLP"],
    created_at: "2026-10-21T11:30:00Z",
    stats: { blocks: 388, figures: 3, tables: 6, formulas: 4, references: 52 },
  },
  {
    id: "33333333-3333-4333-8333-333333333333",
    sha256: "c".repeat(64),
    arxiv_id: "2005.14165",
    version: "v1",
    title: "Language Models are Few-Shot Learners",
    status: "parsing",
    source_kind: "vector",
    page_count: 75,
    tags: ["GPT-3"],
    created_at: "2026-10-25T15:02:00Z",
    stats: { blocks: 1830, figures: 31, tables: 12, formulas: 8, references: 96 },
  },
  {
    id: "44444444-4444-4444-8444-444444444444",
    sha256: "d".repeat(64),
    arxiv_id: null,
    version: null,
    title: "Understanding Deep Learning",
    status: "partial",
    source_kind: "mixed",
    page_count: 541,
    tags: ["教材"],
    created_at: "2026-10-24T08:00:00Z",
    stats: { blocks: 12480, figures: 402, tables: 88, formulas: 610, references: 320 },
  },
  {
    id: "55555555-5555-4555-8555-555555555555",
    sha256: "e".repeat(64),
    arxiv_id: "1706.03762",
    version: "v1",
    title: "Attention Is All You Need",
    status: "ready",
    source_kind: "scanned",
    page_count: 15,
    tags: ["Transformer"],
    created_at: "2026-10-26T10:10:00Z",
    stats: { blocks: 390, figures: 5, tables: 4, formulas: 9, references: 40 },
  },
];

export const mockOutline: OutlineItem[] = [
  { id: "s1", level: 1, title: "1 Introduction", page: 1, block_id: "b1" },
  { id: "s2", level: 1, title: "2 Background", page: 2, block_id: "b40" },
  { id: "s3", level: 1, title: "3 Model Architecture", page: 2, block_id: "b58" },
  { id: "s3-1", level: 2, title: "3.1 Encoder and Decoder Stacks", page: 3, block_id: "b60" },
  { id: "s3-2", level: 2, title: "3.2 Attention", page: 3, block_id: "b71" },
  { id: "s3-2-1", level: 3, title: "3.2.1 Scaled Dot-Product Attention", page: 3, block_id: "b72" },
  { id: "s3-2-2", level: 3, title: "3.2.2 Multi-Head Attention", page: 4, block_id: "b80" },
  { id: "s4", level: 1, title: "4 Why Self-Attention", page: 6, block_id: "b120" },
  { id: "s5", level: 1, title: "5 Training", page: 7, block_id: "b150" },
  { id: "s6", level: 1, title: "6 Results", page: 8, block_id: "b190" },
  { id: "s7", level: 1, title: "7 Conclusion", page: 10, block_id: "b240" },
];

export const mockReferences: Reference[] = [
  { id: "r1", index: 1, raw: "Bahdanau et al. Neural machine translation by jointly learning to align and translate. 2015.", title: "Neural Machine Translation by Jointly Learning to Align and Translate", authors: ["Bahdanau"], year: 2015, doi: null, arxiv_id: "1409.0473", block_id: "b400", bbox: [72, 300, 520, 320], worth_score: 88, worth_reasons: ["在方法章节被提及", "上下文含 build on"] },
  { id: "r2", index: 2, raw: "Sutskever et al. Sequence to sequence learning with neural networks. 2014.", title: "Sequence to Sequence Learning with Neural Networks", authors: ["Sutskever"], year: 2014, doi: null, arxiv_id: "1409.3215", block_id: "b401", bbox: [72, 320, 520, 340], worth_score: 74, worth_reasons: ["在 2 个章节被提及"] },
  { id: "r11", index: 11, raw: "Hochreiter & Schmidhuber. Long short-term memory. Neural Computation, 1997.", title: "Long Short-Term Memory", authors: ["Hochreiter", "Schmidhuber"], year: 1997, doi: "10.1162/neco.1997.9.8.1735", arxiv_id: null, block_id: "b410", bbox: [72, 460, 520, 480], worth_score: 61, worth_reasons: ["在 Related Work 出现"] },
  { id: "r12", index: 12, raw: "Cho et al. Learning phrase representations using RNN encoder-decoder. 2014.", title: "Learning Phrase Representations using RNN Encoder-Decoder", authors: ["Cho"], year: 2014, doi: null, arxiv_id: "1406.1078", block_id: "b411", bbox: [72, 480, 520, 500], worth_score: 33, worth_reasons: ["仅出现在连续合并引用中"] },
  { id: "r13", index: 13, raw: "Kaiser & Bengio. Can active memory replace attention? 2016.", title: "Can Active Memory Replace Attention?", authors: ["Kaiser"], year: 2016, doi: null, arxiv_id: "1610.08613", block_id: "b412", bbox: [72, 500, 520, 520], worth_score: 22, worth_reasons: ["仅出现在 Related Work 罗列中"] },
];

export const mockBlocks: Block[] = [
  { id: "b1", type: "heading", page: 1, bbox: [72, 90, 540, 120], reading_order: 0, section_id: "s1", text: "1 Introduction", latex: null, html: null, asset_id: null, lang: "en", confidence: 1 },
  { id: "b2", type: "paragraph", page: 1, bbox: [72, 130, 300, 420], reading_order: 1, section_id: "s1", text: "Recurrent neural networks, long short-term memory and gated recurrent neural networks in particular, have been firmly established as state of the art approaches in sequence modeling and transduction problems such as language modeling and machine translation [35, 2, 5].", latex: null, html: null, asset_id: null, lang: "en", confidence: 0.99 },
  { id: "b3", type: "paragraph", page: 1, bbox: [312, 130, 540, 420], reading_order: 2, section_id: "s1", text: "In this work we propose the Transformer, a model architecture eschewing recurrence and instead relying entirely on an attention mechanism to draw global dependencies between input and output.", latex: null, html: null, asset_id: null, lang: "en", confidence: 0.99 },
  { id: "b4", type: "formula", page: 3, bbox: [180, 300, 430, 340], reading_order: 3, section_id: "s3-2-1", text: "", latex: "\\mathrm{Attention}(Q,K,V)=\\mathrm{softmax}\\left(\\frac{QK^{T}}{\\sqrt{d_k}}\\right)V", html: null, asset_id: "a9", lang: "en", confidence: 0.94 },
  { id: "b5", type: "table", page: 8, bbox: [72, 200, 540, 380], reading_order: 4, section_id: "s6", text: "Table 2: The Transformer achieves better BLEU scores than previous state-of-the-art models.", latex: null, html: "<table><tr><td>Model</td><td>EN-DE</td><td>EN-FR</td></tr><tr><td>Transformer (base)</td><td>27.3</td><td>38.1</td></tr><tr><td>Transformer (big)</td><td>28.4</td><td>41.8</td></tr></table>", asset_id: "a21", lang: "en", confidence: 0.88 },
  { id: "b6", type: "reference", page: 11, bbox: [72, 460, 540, 480], reading_order: 5, section_id: null, text: "[11] S. Hochreiter and J. Schmidhuber. Long short-term memory. Neural Computation, 9(8):1735–1780, 1997.", latex: null, html: null, asset_id: null, lang: "en", confidence: 0.97 },
];

