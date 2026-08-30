---
name: refresh-accounts
description: One repeatable "refresh" ritual for a YNAB budget -- first runs the categorize-unapproved-transactions pass, then drives a statement-driven reconcile checklist over every non-closed account so nothing silently drifts for months. Reconciliation is anchored to bank statement PDFs as the single source of truth (online/live balances are NOT trusted -- Chase->YNAB import lag exceeds the balance difference); an account with no statement PDF is skipped-with-reason, never reconciled against a live balance. Drift is measured with the anchor-independent monthly-net-diff method (statement activity vs YNAB cleared activity), not current-balance-minus-register, which phantom entries contaminate. Use this whenever the user wants to fully refresh / catch up / reconcile their YNAB accounts, do a monthly account cleanup, or "make sure everything is reconciled" -- triggers on /refresh-accounts as well as natural language like "refresh my accounts," "reconcile everything," or "catch up the budget."
allowed-tools: mcp__ynab__list-accounts mcp__ynab__list-transactions mcp__ynab__lookup-entity-by-id AskUserQuestion Bash
---

# Refresh Accounts

## Overview

Accounts drift when nothing forces a reconcile. This skill makes account upkeep a single
ritual: it runs the categorization pass, then walks **every non-closed account** and produces
a statement-anchored reconcile checklist, refusing to report "done" until each account is
either reconciled or explicitly skipped-with-a-reason.

Two hard rules, both learned the hard way (17 months of Chase Checking drift hiding a scam
check and a pile of phantom transactions):

1. **Bank statements are the single source of truth.** Online balances -- *present* and
   *available* -- are NOT trustworthy for reconciling here: the Chase->YNAB cleared-transaction
   import lag can exceed the balance difference. An account with **no statement PDF cannot be
   reconciled** — skip it with reason "awaiting statement". Never fall back to a live balance.
2. **Drift is measured by the monthly-net-diff method, never `current_balance - register`.**
   The latter is contaminated by phantom / externally-generated composite-id entries (it gave
   three different wrong numbers on one account). The bundled script uses the immune method.

**Announce at start:** "Using the refresh-accounts skill: categorize first, then reconcile
every account against its bank statement."

## Workflow

### Step 1 — Categorize

Resolve `budget_id` (ask via `AskUserQuestion` if ambiguous). **Invoke the
`categorize-unapproved-transactions` skill** for the budget and let it run to completion
(including its own no-approvals safety check). Do not reimplement categorization here.

### Step 2 — Enumerate accounts

Call `list-accounts`. The working set is every account with `closed == false`. Note each
account's `name`, `id`, `cleared_balance`, and `last_reconciled_at` (a stale or null
`last_reconciled_at` is exactly what this skill exists to catch).

### Step 3 — Find each account's statement PDF (hard gate)

Statements come from a configured directory (default `YNAB_STATEMENTS_DIR`, e.g. the user's
Dropbox `Finances/Statements`) or a per-run override path the user provides. For each account,
locate the **newest** matching statement:
- Chase accounts: the filename carries the account tail (e.g. `0033`, `8659`).
- Ally accounts: one **combined** statement per period (no tail in the filename); the script
  splits accounts apart by tail when it parses.

**If no statement PDF exists for an account, record it as `skipped` with reason "awaiting
statement" and move on — do NOT reconcile it against any online balance.** This is the whole
point: an unreconcilable account is surfaced, not papered over.

### Step 4 — Per-account drift report

For each account that has a statement, run the bundled script (read-only against YNAB):

```bash
uv run python .agents/skills/refresh-accounts/scripts/reconcile_report.py \
  --budget-id <budget-id> --account-id <account-id> --statement <path.pdf> \
  [--account-tail <NNNN>]   # required only for Ally combined statements
```

It parses the statement (period + closing balance), compares to the account's cleared
activity via the monthly-net-diff method, and prints a JSON report + a one-line summary. The
**`ynab_activity_drift`** field is the trustworthy signal (in-period activity vs the
statement); `ynab_balance_drift` / `expected_adjustment` are best-effort (the balance-anchor
piece can still be biased by pre-close phantom entries, so treat them as a guide, not gospel).

### Step 5 — Present the reconcile checklist

Produce a per-account table: `last_reconciled_at`, statement period + closing balance, the
activity drift, the expected adjustment, and any uncleared/phantom items the user should
resolve first. For each reconcilable account, tell the user exactly what to do in the YNAB
app: **open Reconcile, enter the statement's CLOSING balance (not a live online balance),
mark the through-statement-date transactions cleared, and accept the small adjustment.** The
skill does not reconcile via API (there is no reconcile endpoint, and auto-writing an
adjustment off drift math is unsafe) — it guides; the user clicks.

### Step 6 — Track completion

The skill is **not done** until every non-closed account is either (a) reported reconciled by
the user, or (b) explicitly `skipped` with a recorded reason. List both buckets in the final
summary. A large `activity_drift` on any account is a flag to investigate (missing/duplicate
transactions, a mis-recorded transfer) before reconciling — offer to dig in.

## Safety

- **Read-only reconcile layer.** The bundled script only reads balances/transactions; it never
  writes, approves, or reconciles. All writes come from Step 1's `categorize-unapproved-transactions`,
  which carries its own never-approve guarantee and independent verification.
- **Statement-only.** If tempted to reconcile against an online balance because a statement is
  missing, don't — that is the exact failure mode this skill prevents.

## Bundled script

`scripts/reconcile_report.py` — talks to YNAB directly via this repo's own
`ynab_mcp.client`/`ynab_mcp.config` (same `YNAB_PAT`), independent of any MCP tool call; parses
statement PDFs with `pypdf`; computes drift via `ynab_mcp.reconcile`. Run it with
`uv run python` from the repository root.
