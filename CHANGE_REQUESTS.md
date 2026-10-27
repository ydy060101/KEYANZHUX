# Change requests

Append-only. Each entry states the reason, blast radius and proposal, and the
contract stays unchanged until a human approves it (AGENTS.md §2.3).

## CR-001 — Make and Docker are unavailable on this host

- **Request:** Replace `make` acceptance commands with `tools.ps1`, and treat the
  Docker Compose startup in T0.6 as optional.
- **Reason:** Neither GNU Make nor Docker is installed, and the user has stated
  they will not install them.
- **Impact:** Every card's acceptance command becomes `.\tools.ps1 accept` plus
  card-specific checks. T0.6's one-command startup is delivered as
  `tools.ps1 db-up` + `tools.ps1 dev` against a portable PostgreSQL/Redis pair.
- **Proposal:** Keep `docker-compose.yml` in the repository as the documented
  path for environments that do have Docker; document the portable runtime as
  the supported path on this machine.
- **Status:** Applied in T0.1. Awaiting human approval.

## CR-002 — Light-theme state colours are below the 4.5:1 text contrast target

- **Request:** Review `--accent`, `--warn`, `--danger`, `--success` when used as
  small text on `--bg` / `--surface`.
- **Evidence:** On `#F7F8FB`, contrast ratios are accent 2.34, warn 2.02,
  danger 3.54, success 2.39 — all below 4.5:1.
- **Impact:** The tokens are kept unchanged for fills and state backgrounds. Four
  darker companions (`--accent-text`, `--warn-text`, `--danger-text`,
  `--success-text`) are added for text use, so the 4.5:1 requirement in 02 §5 is
  met without changing the specified palette.
- **Status:** Applied in T0.4. Awaiting human approval.

## CR-003 — `VersionDiff` needs a `comparable` flag

- **Request:** Add an optional boolean `comparable` to `VersionDiff` in
  `openapi.yaml`.
- **Reason:** When either version has not finished parsing, `diff_sections`
  finds no sections and every count is zero. The summary then read "两版本间无
  任何变化", which is false: the documents were simply not comparable yet. The
  client cannot tell the two cases apart from the existing fields, because an
  empty `sections` array is also the correct result for two identical parsed
  versions.
- **Impact:** Additive and optional; existing clients ignore it. `summary` stays
  within its 200-character limit and keeps the same grounding rules.
- **Proposal:** Add `comparable: { type: boolean }` to `VersionDiff`; when it is
  false the summary says the comparison is not yet possible instead of claiming
  no changes.
- **Status:** Applied in T1.6. Awaiting human approval.

## CR-004 — `Document.stats` needs citation coverage counters

- **Request:** Add `citations`, `cited_references`, `uncited_references` and
  `dangling_citations` to the `stats` object of `Document` in `openapi.yaml`.
- **Reason:** The T2.3 card requires "覆盖率统计写入文档状态", and the contract's
  `stats` currently stops at `references`. Without the counters a client can
  tell that a paper has 40 references but not whether the body cites them —
  which is exactly the case where the citation extraction silently failed.
  `GET /documents/{id}/citations` is specified as a bare array, so the numbers
  have nowhere else to go without changing that shape.
- **Impact:** Additive and optional; existing clients ignore the new keys. The
  values are computed from the `citations`/`references` rows on every read, so
  they cannot drift from the data they describe.
- **Proposal:** Extend `stats` with the four integer counters.
- **Status:** Applied in T2.3. Awaiting human approval.

## CR-005 — A table for the section-level index

- **Request:** Add a `section_summaries` table: `doc_id`, `section_id`, `title`,
  `page`, `summary`, `block_ids[]`, with a primary key on `(doc_id, section_id)`.
- **Reason:** T2.5 requires "章节摘要两级索引" — a section level above the block
  chunks 01 §9 defines. 01 §4 lists `chunks` with `section_id`, which lets a
  chunk name its section but gives the section no row of its own: there is
  nowhere to hold a section's title, page and summary, so the coarse level of
  the index cannot be stored or queried. 01 §4 calls its table list a "最小集合",
  so a table is not excluded in principle, but adding one is still a contract
  change and is recorded here rather than made silently.
- **Impact:** Additive. No existing table, column, API path or field changes.
  The summary is extractive (the section's own opening sentences) rather than
  LLM-generated, so it needs no anchor column and cannot invent content (H02).
- **Proposal:** Add the table with `(doc_id, section_id)` as its key; write it
  from the windowed parse as each window's sections close.
- **Status:** Applied in T2.5. Awaiting human approval.

## CR-006 — A `meta` column on `documents`

- **Request:** Add `documents.meta` as `JSONB NOT NULL DEFAULT '{}'`.
- **Reason:** T2.6's 概览 card shows title, authors and abstract, and each of
  them carries the anchor H01 requires. 01 §4's `documents` table has a `title`
  column but no place for authors, abstract or their anchors, so the reader
  could either show unanchored metadata (forbidden by H01) or re-parse the PDF
  on every open. The column stores the `DocMeta` model serialised whole, so a
  field added to the model cannot be silently dropped on the way to storage.
- **Impact:** Additive. No existing column, API path or field changes. The
  value is written by the parse job and read by `/structure`.
- **Proposal:** Add the column with an empty-object default.
- **Status:** Applied in T2.6. Awaiting human approval.

## CR-007 — `assets.html` for table rendering

- **Request:** Add `assets.html` as nullable `text`.
- **Reason:** T2.6 requires tables to render as HTML with a 查看原图 toggle
  (02 §4.2). `assets` holds the crop's `path` and its `bbox`, which supports the
  image half only; the parser already computes `table.to_html()` but there was
  nowhere to keep it, so the reader could not show the structure without
  re-parsing. Figures and formulas leave it NULL.
- **Impact:** Additive and optional. Existing clients ignore the field.
- **Proposal:** Add the nullable column and fill it for `kind = "table"`.
- **Status:** Applied in T2.6. Awaiting human approval.

## CR-008 — `section_summaries.level`

- **Request:** Add `section_summaries.level` as `integer NOT NULL DEFAULT 1`.
- **Reason:** The reader renders the outline as a tree. The depth was being
  recovered in the API from the title's numbering (`2.1` → level 2), which
  fails for an unnumbered heading — the book's front matter has several. The
  parse already knows the level (it is what the heading rule decided), so it is
  stored rather than re-guessed at read time.
- **Impact:** Additive. No existing column changes.
- **Proposal:** Add the column and write it from `rag/index.py`.
- **Status:** Applied in T2.6. Awaiting human approval.

## CR-009 — `page` on citation and reference payloads

- **Request:** Add `page: integer | null` to the `Citation` and `Reference`
  response objects in `openapi.yaml`.
- **Reason:** The reader has to draw a marker's hit box on the page the marker
  sits on, and to scroll to a bibliography entry's page. Without the field the
  client would have to derive the page from `block_id` (`b12_3` → 12), which
  copies an internal id scheme into TypeScript and breaks silently if the scheme
  ever changes.
- **Impact:** Additive and optional; existing clients ignore it. The value is
  derived from the block id on the server, where the scheme lives.
- **Proposal:** Add the field to both schemas and to the payload builders.
- **Status:** Applied in T2.6. Awaiting human approval.

## CR-010 — `level` on the outline payload

- **Request:** Add `level: integer` to each `outline` item in
  `GET /documents/{id}/structure`.
- **Reason:** The outline is a tree (02 §4.2: 可折叠标题树). CR-008 stored the
  depth on `section_summaries`, but the payload did not carry it, so the reader
  would have to infer nesting from the title text — exactly what CR-008 exists
  to stop doing.
- **Impact:** Additive. The field is read from the row that already holds it.
- **Proposal:** Add the field to the outline item schema and its builder.
- **Status:** Applied in T2.6. Awaiting human approval.

## CR-011 — `POST /documents/{id}/embed` and chunk counters on the detail payload

- **Request:** Add `POST /documents/{id}/embed` (202, returns `{doc_id, job_id}`)
  and `chunks` / `embedded` / `sections` on `Document.stats`.
- **Reason:** 01 §7 stage 10 puts chunking, embedding and indexing together, but
  the embedding model is a 2 GB local model that takes minutes to load and is
  unavailable on a machine that has not downloaded it. Making it a step of the
  parse would mean no window is searchable until the model is there, which
  contradicts T2.5's acceptance ("已完成窗口可提前检索") and H08 (degrade, do not
  block). A separate job also gives the user a retry once the model is present.
  The counters exist because the pass is separate: without them a client cannot
  tell a document that is fully embedded from one that is only chunked.
- **Impact:** Additive. One new path, three new optional fields in an object that
  already carries an open set of counters. `kind="embed"` joins the job kinds.
- **Proposal:** Add the path and the fields; the parse still writes chunks with
  `embedding` null.
- **Status:** Applied in T3.1. Awaiting human approval.
