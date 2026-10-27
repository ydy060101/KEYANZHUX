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
| T2.4 Scanned OCR | not started | |
| T2.5 Long book pipeline | not started | |
| T2.6 Reader (structure and render) | not started | |

## Stage 3 — Anti-hallucination QA

| Card | Status | Notes |
|---|---|---|
| T3.1 Chunking and indexing | not started | |
| T3.2 Hybrid retrieval | not started | |
| T3.3 QA with provenance | not started | |
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
