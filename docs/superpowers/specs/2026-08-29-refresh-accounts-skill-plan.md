# `/refresh-accounts` skill — implementation plan

> Issue #36. Design: `2026-08-29-refresh-accounts-skill-design.md`. Execute tasks top-down; each is TDD (RED → GREEN → refactor), committed + pushed on completion.

## Architecture

Mirror the repo's pure-logic-in-`src/`, I/O-in-script split (`amazon_matching.py` is the
precedent). Pure, fixture-testable functions live in **`src/ynab_mcp/reconcile.py`**; the
**skill script** (`.agents/skills/refresh-accounts/scripts/reconcile_report.py`) does PDF +
YNAB I/O and calls them. No real financial data in fixtures — pure functions are tested with
synthetic *text/number* inputs, so no committed statement PDFs.

## Task 1 — `ynab_mcp.reconcile.parse_statement_text` (pure)

`parse_statement_text(text: str) -> StatementInfo` — regex-extract from statement text:
`bank` ("chase" | "ally"), `account_tail` (e.g. "0033"/"8659"/"5181"), `period_start`,
`period_end` (dates), `beginning_balance`, `ending_balance`. Raise a clear error on
unrecognized format.
- **RED**: `tests/test_reconcile.py` with synthetic Chase and Ally statement text snippets
  (crafted, non-real) → asserts each field; asserts a `StatementParseError` on garbage.

## Task 2 — `ynab_mcp.reconcile.compute_drift` (pure)

`compute_drift(statement, ynab_net_over_period, ynab_cleared_as_of_close) -> DriftResult`
carrying: `statement_net` (= end − begin), `activity_drift` (= ynab_net_over_period −
statement_net), `balance_drift` (= ynab_cleared_as_of_close − ending_balance), and
`expected_adjustment` (what the user will enter). Pure arithmetic.
- **RED**: cases incl. exact-match (0 drift), a residual, and a case whose register contains
  phantom entries in `ynab_net_over_period` to show the method still reports the true
  activity drift (immunity assertion).

## Task 3 — `ynab_mcp.reconcile.resolve_statement_file` (pure)

`resolve_statement_file(account, filenames, override=None) -> str | None` — given an account
(name + tail) and a list of candidate filenames from the config dir, pick the newest matching
statement (tolerant of Chase's shifting conventions: `YYYYMMDD-statements-<tail>-.pdf`,
`<tail> - Checking - Mon DD, YYYY.pdf`, `mon_dd_yyyy_statement.pdf` for Ally). Return `None`
when nothing matches (→ skip-with-reason). Override path short-circuits.
- **RED**: filename lists across all three conventions + no-match → `None`.

## Task 4 — `reconcile_report.py` script (I/O orchestration)

CLI under the skill's `scripts/`: resolve {account → PDF} (config dir via `YNAB_STATEMENTS_DIR`
+ per-run overrides), extract text via **`pypdf`**, call the Task 1–3 functions, pull YNAB
cleared transactions via `ynab_mcp.client` (`call_with_retry`), compute per-account drift, emit
JSON checklist + human summary. No-PDF accounts → `skipped` with reason. Read-only against YNAB.
- Verified by a fixture-based test that stubs the PDF-text + YNAB-fetch boundaries (no real data,
  no network) and asserts the no-statement path yields `skipped`, not a reconcile.

## Task 5 — `SKILL.md`

Harness-agnostic (`.agents/rules/shared/harness-agnostic-skills.md`): Step 1 delegates to
`categorize-unapproved-transactions`; Steps 2–8 per the design workflow; statement-required hard
gate; guide-don't-auto-reconcile; never-approve. Reference the bundled script.

## Task 6 — Docs

AGENTS.md skills table + `## Skills` prose; CHANGELOG entry.

## E2E / acceptance

`make pr_check` (lint + tests) green. A live test-kit handoff: run `/refresh-accounts` against
Rench Budget with the real Dropbox statements, confirm it categorizes then produces the
per-account checklist and correctly skips any account lacking a statement.
