# `/refresh-accounts` skill — design

> Issue: #36 (parent epic #10). Companion plan doc: `2026-08-29-refresh-accounts-skill-plan.md`.

## Problem / motivation

Rench Budget's Chase Checking sat **unreconciled for 17 months**. That silence hid a
$2,190.41 scam check (marked "SCAMMERS", left uncleared), a pile of phantom
externally-generated transactions, and genuine drift — none of which surfaced because
nothing ever *forced* a reconcile. Two hard lessons from digging out of it drive this skill:

1. **Online balances are not trustworthy for these accounts.** chase.com's *present*
   and *available* balances were both >$2K off from YNAB's cleared balance, and the gap
   was Chase→YNAB import lag (cleared transactions lag even the posted balance), not real
   error. **Bank statements (closed periods) are the only reliable single source of truth.**
2. **The naive drift check lies.** `current_cleared_balance − Σ(register)` is contaminated
   by phantom / auto-generated composite-id entries — it produced three different wrong
   numbers ($2,326 low, $538 high, $2,568 high) on the same account. The
   **anchor-independent monthly-net-diff method** (compare YNAB's cleared *activity* to the
   statement's *activity*) is immune to that contamination and is what this skill uses.

## Goal

One `/refresh-accounts` ritual that (1) runs the existing categorization pass, then
(2) drives a **statement-driven** reconcile checklist over **every** non-closed account,
and refuses to report "done" until each account is reconciled or explicitly
skipped-with-a-reason.

## Design decisions

1. **Reuse, don't duplicate** — Step 1 invokes `categorize-unapproved-transactions`; this
   skill adds only the reconcile layer.
2. **Statement PDF is REQUIRED per account** (the SSOT). No statement → the account is
   **skipped-with-reason** ("awaiting statement"); the skill never falls back to an online
   balance. This is a hard gate, not a warning.
3. **Statement input = configured directory + per-run override.** Default: a configured
   statements folder (e.g. the user's Dropbox `Finances/Statements`) from which the skill
   auto-picks the latest statement per account by filename; any account's PDF can be
   overridden with an explicit path per run. Config via skill argument / env
   (`YNAB_STATEMENTS_DIR`).
4. **Drift = monthly-net-diff.** For the statement's own period, compare
   `(statement ending − statement beginning)` against YNAB's **cleared net** over that same
   date range, and compare the statement's ending balance against YNAB's cleared balance
   **as of the statement close date** (not "now" — that's what import-lag poisons). Report
   the residual as the expected reconciliation adjustment.
5. **Guide, don't auto-reconcile.** The YNAB API has no reconcile endpoint, and auto-posting
   a balance adjustment off drift math is exactly what burned us. The skill *computes and
   presents* the per-account checklist + exact expected adjustment; the **user performs the
   final Reconcile in the YNAB app** (mark cleared, enter the statement's closing balance).
   No reconcile-driven writes.
6. **Never approve** — inherits `categorize-unapproved-transactions`' guarantee; the reconcile
   layer is read-only against YNAB (it only reads balances/transactions).

## Workflow (SKILL.md)

1. Resolve `budget_id`. Announce intent.
2. **Categorize** — invoke `categorize-unapproved-transactions` for the budget.
3. Enumerate non-closed accounts (`list-accounts`).
4. For each account, **locate its statement PDF**: per-run override if given, else newest
   match in the configured directory. **No PDF → record skip-with-reason and continue.**
5. **Parse** the statement (bank-format-aware: Chase `0033`/`8659`, Ally): statement period
   start/end, beginning + ending balance.
6. **Compute drift** (monthly-net-diff + cleared-balance-as-of-close-date vs statement ending).
7. Emit the **per-account reconcile checklist**: last-reconciled date, statement close
   date + balance, YNAB cleared balance as-of-close, drift, any uncleared/phantom items to
   resolve first, and the exact adjustment to expect.
8. User reconciles each account in the YNAB app to its statement. The skill does **not**
   report complete until every account is reconciled-or-skipped (tracked explicitly).
9. Structured + human summary.

## Bundled script

`scripts/reconcile_report.py` (run via `uv run python`, like
`categorize-unapproved-transactions/scripts/check_no_approvals.py`): talks to YNAB directly
through the repo's own `ynab_mcp.client`/`ynab_mcp.config` (same `YNAB_PAT`), independent of
any MCP tool call.

- Input: budget id + an {account → statement-PDF} mapping (resolved from config dir or overrides).
- Statement parsing via **`pypdf`** (the local machine has no `poppler`/`pdftotext`; `pypdf`
  works and is already the proven path). Bank-format detection keys off statement text
  ("JPMorgan Chase" vs "Ally Bank") and account-number tails.
- Pulls YNAB cleared transactions; computes monthly-net-diff + cleared-as-of-close-date.
- Output: per-account checklist as JSON (stable field names, for future trend/report reuse)
  + a human-readable summary.

## Testing

- **Statement parsing** — fixture PDFs (Chase `0033`, Chase `8659`, Ally) → asserts correct
  period + beginning/ending balances; bank-format detection.
- **Drift computation** — synthetic YNAB cleared nets vs statement nets → asserts the
  monthly-net-diff and residual adjustment are correct, incl. a case with phantom entries
  present to prove immunity.
- **Skill** — harness-agnostic `SKILL.md`; a fixture-based script test proving the
  no-statement path skips-with-reason rather than reconciling.

## Deferred / future

- Full statement-*transaction* extraction (line-by-line audit) — the balances + period are
  sufficient for the single-statement drift check now; deeper audit is a later enhancement.
- Auto-posting reconciliation adjustments — deferred until the drift math is trusted.
- Robustness to Chase's shifting filename conventions (already changed once) — the config-dir
  matcher parses account tail + date from the filename with tolerant patterns; documented as a
  known maintenance point.
