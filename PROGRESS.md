# Project state

Filled in as task cards complete. A card is only checked when its acceptance
command passes and its commit exists.

## Stage 0 — Foundation

| Card | Status | Notes |
|---|---|---|
| T0.1 Repo and toolchain | complete | `tools.ps1 accept` green: ruff, eslint, mypy, tsc, 6 pytest, 4 vitest, vite build. |
| T0.2 Contract implementation | complete | 21 tables created on PostgreSQL 17.6 + pgvector 0.8.7; Pydantic document model matches 01 §3. OpenAPI file pending. |
| T0.3 LLM gateway | complete | Retries, rate limit, cache, JSON-schema retry, injection guard, FakeLLM. 6 tests. |
| T0.4 Design system and shell | not started | |
| T0.5 Six-page mock prototype | not started | |
| T0.6 One-command startup | not started | |

## Stage 1 — Ingest and dedup

| Card | Status | Notes |
|---|---|---|
| T1.1 Job system | complete | `jobs` table + arq + in-process fallback; cancel/retry; SSE `/jobs/stream`. 15 pytest. |
| T1.2 Upload and CRUD | complete | Multi-file upload, H09 validation, sha256 idempotency, PATCH/DELETE, Range streaming (206/416). 11 pytest. |
| T1.3 Vector parsing | complete | Stages 1-3/5 with anchored metadata; verified on Transformer (8 authors), BERT (4), GPT-3 (31). 6 pytest. |
| T1.4 Semantic dedup | complete | L1 sha256, L2 arXiv version, L3 cosine+MinHash; resolve keep_existing/replace/keep_both. Case 3.1 passes through the API. 11 pytest. |
| T1.5 Version diff | complete | Section-level diff, stats, LLM summary whose digits must appear in the stats. v1 vs v7: 13 modified sections, 4 new refs. 12 pytest. |
| T1.6 Library page on real API | complete | Real `/documents` + SSE progress + dedup dialog + version diff; mock only behind `VITE_USE_MOCK`. DoD verified by `frontend/e2e/verify-ui.mjs` at 1440×900 / 1280×720 in both themes, zero console errors. 18 pytest for documents. |

## Stage 2 — Parsing and reader

| Card | Status | Notes |
|---|---|---|
| T2.1 Heading tree | complete | Bookmarks first, font-size+numbering fallback with sequence validation, max 3 levels. Transformer 22 headings (3 levels), BERT 25 (rules only), GPT-3 32 — all matching the printed contents. 12 pytest. |
| T2.2 Figures, tables, formulas | complete | Caption pairing, table-body extension, symbol-density formula detection; every asset keeps a 2× page crop. v1: 5 figures, 4 tables, 13 formulas. Sub-figure labels (3.2) keep their own ids. 11 pytest. |
| T2.3 References and citation markers | complete | Link annotations first, regex per-page fallback; markers split across links are rejoined. v1 36/36 cited, v7 40/40, GPT-3 144/144, BERT 52/56 — zero dangling. Reference parsing handles numbered, alpha-keyed and unnumbered (margin-split) bibliographies. Coverage in `stats` (CR-004). 18 pytest. |
| T2.4 Scanned OCR | complete | Page probe → OCR only on text-free pages → same document model. PaddleOCR 3.7 (PP-OCRv5 mobile, 2× render), ~5s/page; bbox and confidence kept on every block (H01). The scan restores title, abstract, all 24 printed headings (1–7 incl. "6 Results", subsections, References), 36 references and 5 figures/4 tables; raw OCR vs the vector text layer is 0.95 shingle containment. Dedup is re-run after OCR: the scan scores 0.844 against its vector original (unrelated fixtures 0.000), so it is reported as content_duplicate with both copies kept. Fixes 3 parser defects found on the way (word gaps dropped, headings needing a space, caption separator). 15 pytest. |
| T2.5 Long book pipeline | complete | 20-page windows, page-scoped ids (`b{page}_{n}`, `eq{page}_{n}`) stable across resume. End-to-end on the 541-page book via the real handler: 28 windows, 32.2 s, 10748 blocks over 537 content pages (2, 4, 10, 12 are blank in the source), 1138 chunks, 169 section summaries, 1014 headings. Peak RSS 859 MB against the 4096 MB limit, flat per window (764→857 over 28). Every window publishes its own progress event and its chunks are queryable before the parse ends. Resume replays stored blocks through the same tracker and chunker. `tools/check_long_book.py` reports **B3: PASS**. 15 pytest in `test_windows.py` plus 4 slow tests in `test_long_book.py`. |
| T2.6 Reader (structure and render) | complete | Three rails: outline/thumbnails, pdf.js pages with a real text layer, and a 结构/问答/翻译 panel. Only the visible pages ±2 keep a bitmap (IntersectionObserver), so the 541-page book opens in **1.24 s** against the 2 s limit. Outline comes from `section_summaries` (169 rows, filterable, `data-outline-id` on each) rather than heading-typed blocks (1014, only 169 unique ids — the source of the duplicate-key crash). Citation markers are hit boxes over the page from the recorded bbox; hovering shows title/authors/year/含金量 and 跳转|入库, clicking scrolls to the entry, and the entry's 返回引用处 jumps back and draws the anchor highlight for 3 s. Structure panel renders table HTML with a 查看原图 toggle, KaTeX formulas, figures, references and the metadata card. Six defects fixed on the way: a caption need not be punctuated after its number — the book prints 290 as "Figure 1.1 Machine learning is an area of…", and requiring a colon had left its figure and table lists empty; the table detector is asked with all three strategies and must return a box inside the crop, because its `text` strategy returns one box spanning the whole page and the old overlap test accepted it; the end-of-parse bibliography pass appended instead of replacing (a re-parse died at 97% on the citations primary key); the regex citation fallback accepted `[0, 1]`/`r[0]`/`log[1]` as citations and anchored them to whole paragraphs; the book's two-column bibliography was split at one book-wide margin (605 entries, one 4661 chars) and absorbed the running head and colophon (704 with furniture) — now per-page columns with page-wide spans excluded, **1198 entries across 50 pages**, zero dangling; the hover card closed before the pointer could reach it; 46 link groups merged two citations across a semicolon (`95; Cr 1997`), so a marker containing one is now counted as unresolved rather than recorded. Book now: 541 pages, 1 198 references, 3 243 citations, 0 dangling, **272 figure crops** (was 0), 1 797 formula crops. 7 structure + 22 citation + 17 asset pytest, 20 vitest; `frontend/e2e/verify-reader.mjs` PASS and `frontend/e2e/check-reader-viewports.mjs` PASS at 1440×900 / 1280×720 in both themes. |

## Stage 3 — Anti-hallucination QA

| Card | Status | Notes |
|---|---|---|
| T3.1 Chunking and indexing | complete | Chunks are aggregated whole blocks, never crossing a section, with `block_ids[]` on every row so a hit maps back to an anchor (H01). bge-m3 vectors are filled by their own job (`kind="embed"`, `POST /documents/{id}/embed`), because a 2 GB model must not gate the parse (CR-011); the pass is resumable, idempotent, and fails loudly when the model is missing (H08) rather than reporting success with no vectors. HNSW (`m=16`, `ef_construction=64`, `vector_cosine_ops`) and a GIN index over the generated `tsv` are declared on the table and added to an existing database by `tools/sync_schema.py`. Two chunker defects found on the fixtures and fixed: 54 blocks of Transformer v1 and 76 of GPT-3 have no letter in them (folio numbers, a stray √) and each was becoming a chunk whose whole text was "3"; and an overlap tail that closed on its own after a section break was emitted as a chunk wholly contained in its predecessor (2 in GPT-3). Real model verified: 45 chunks of Attention v1 embedded in 51 s, and 3/3 probe queries return the passage that answers them (score spread 0.148 over the top 20) — `tools/check_embedding.py` reports **E1: PASS**. 26 pytest in `test_rag_index.py`. |
| T3.2 Hybrid retrieval | complete | 01 §9's pipeline in order: BM25 over the GIN-indexed `tsv` (top 30) + cosine over the HNSW-indexed vectors (top 30) → RRF (`rrf_k=60`) → bge-reranker top 8. Every hit carries `chunk_id`, `block_ids[]`, section and page range, so the answer layer builds an anchor without another query (H01). `scope` is `doc`/`set`/`all`; an empty `doc`/`set` matches nothing rather than the whole library. Degradation is per stage and reported (`stages.vector`, `stages.reranked`), so a BM25-only ranking is never mistaken for a full one (H08). Two defects found by the real-model run and fixed: `websearch_to_tsquery` AND-ed the question's words and returned nothing for 5 of 8 golden questions (now an OR-query rebuilt from `[A-Za-z0-9]+` runs, 27–30 candidates each); and the acceptance script had been checking block mapping against an empty `blocks` table, not a pipeline bug. Real models: **R1: PASS** — recall@8 1.00 (8/8), chunk→block mapping 8/8, scope isolation ok — `tools/check_retrieval.py`. 20 pytest in `test_retrieval.py` + `test_retrieval_scope.py` (stub embedder, recall@8 0.88). Models are loaded `local_files_only` when the cache already has them, so a present 2 GB model no longer triggers a hub round trip. |
| T3.3 QA with provenance | complete | `POST /qa` streams `token` → `anchor` → `done` (or `error` in the H17 envelope) over SSE, with a keepalive while retrieval/rerank/generation run. Pipeline: retrieve (T3.2) → H03 refusal when the reranker's top score < `QA_MIN_SCORE` → targeted extraction for metadata questions (fast tier; a field survives only if its value occurs verbatim in the block it cites, otherwise null) → evidence-numbered generation (`strong`, temperature 0) → H04 sentence-level verification → marker-to-anchor mapping → events. H04 drops uncited sentences (`uncited_claim`), ungrounded numbers/names/formulas (`ungrounded_number`) and out-of-range markers (`invalid_citation`); if nothing survives, the answer is the refusal card rather than an unsupported conclusion (H01). The anchor is the block containing the rarest verified token, so a chunk spanning a page break lands on the page where its number is. Generation is buffered and emitted per verified sentence: H04 needs a whole sentence before display and H06's cache only applies to non-streaming calls. `mode=compare` is rejected with `mode_not_implemented` until T3.4. **Q1: PASS** — `tools/check_qa.py` on real bge-m3 + bge-reranker + DeepSeek: anchor page accuracy **20/20 (1.00)** against the 0.90 target, refusal **5/5 (1.00)**, point hit rate 20/20; the golden set is 20 single-doc questions + 5 unanswerable ones in `tests/golden_qa.json`, every needle checked against the fixture's pages by `tests/test_golden_qa.py`. First acceptance run was 19/20: q17's chunk spans pages 6–7 and a match-count tie anchored page 6 while the quote stopped before "36M"; fixed by weighting matched tokens by 1/frequency in both anchor and quote selection. 31 pytest in `test_qa.py` + `test_qa_verify.py`, 4 in `test_golden_qa.py`. |
| T3.4 Multi-document compare | not started | |
| T3.5 QA frontend | not started | |
| T3.6 Evaluation script | not started | |

## Stage 4 — Translation

| Card | Status | Notes |
|---|---|---|
| T4.1 Selection translation | not started | |
| T4.2 Full-document translation | not started | |
| T4.3 Bilingual linked scrolling | not started | |
| T4.4 Translation cache and glossary | not started | |

## Stage 5 — Discovery and recommendation

| Card | Status | Notes |
|---|---|---|
| T5.1 Search and download | not started | |
| T5.2 Worth score and batch import | not started | |
| T5.3 arXiv tracking | not started | |
| T5.4 Recommendation and feedback | not started | |
| T5.5 Multi-user | not started | |
| T5.6 Discover page frontend | not started | |

## Stage 6 — Graph and survey

| Card | Status | Notes |
|---|---|---|
| T6.1 Citation matching and graph | not started | |
| T6.2 Graph algorithms | not started | |
| T6.3 Graph frontend | not started | |
| T6.4 Domain survey | not started | |
| T6.5 Future Work filtering | not started | |

## Stage 7 — Writing and visualization

| Card | Status | Notes |
|---|---|---|
| T7.1 Outline and reference verification | not started | |
| T7.2 Figure scripts and sandbox | not started | |
| T7.3 Data charts and captions | not started | |
| T7.4 Academic translation | not started | |
| T7.5 Writing studio frontend | not started | |

## Stage 8 — Polish and delivery

| Card | Status | Notes |
|---|---|---|
| T8.1 Experience polish | not started | |
| T8.2 Performance and stability | not started | |
| T8.3 End-to-end and demo script | not started | |
| T8.4 Docs and delivery | not started | |
| T8.5 Full regression | not started | |
