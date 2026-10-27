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
