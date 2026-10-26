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
