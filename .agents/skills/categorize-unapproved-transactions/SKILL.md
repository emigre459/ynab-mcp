---
name: categorize-unapproved-transactions
description: Best-effort categorizes not-yet-approved transactions in a YNAB budget, using the existing find-payee-transactions and find-amazon-transactions tools as evidence. Writes category_id only for transactions backed by hard evidence (a real matched Amazon order's item text, or a strong historical payee-category pattern) and leaves everything else for human review -- never approves a transaction, and independently verifies that with a deterministic script rather than trusting its own behavior. Use this whenever the user wants to categorize unapproved or uncategorized YNAB transactions, clean up their YNAB approval queue, process pending transactions, or run a monthly categorization pass -- triggers on /categorize-unapproved-transactions as well as natural language like "categorize my unapproved transactions," "clean up the YNAB inbox," or "what categories should these pending transactions get."
allowed-tools: mcp__ynab__list-transactions mcp__ynab__list-categories mcp__ynab__find-payee-transactions mcp__ynab__find-amazon-transactions mcp__ynab__bulk-manage-transactions AskUserQuestion Bash
---

# Categorize Unapproved Transactions

## Overview

Not-yet-approved YNAB transactions sit uncategorized or miscategorized until someone reviews them by hand. This skill closes most of that gap automatically: it reads every unapproved transaction, gathers real evidence for what each one actually was, and writes a category for the ones evidence genuinely supports — leaving the rest for a human, clearly labeled with why.

The one rule this skill can never bend: **it writes categories, never approvals.** `approved` never appears in any write this skill makes, and a bundled script independently proves that after the fact rather than asking you to take the skill's word for it.

**Announce at start:** "Using the categorize-unapproved-transactions skill to best-effort categorize unapproved transactions."

## Why evidence tiers, not "categorize everything"

An earlier live run of this workflow used keyword rules to guess categories from Amazon item descriptions, and found real false positives: a storage-bag-and-detergent order got tagged "Medical" because its marketing copy mentioned "First Aid Kits" as a use case, and a smartwatch got tagged "Home Supplies" because its description mentioned "battery life." Naive pattern matching on free text is unreliable in exactly the cases that matter — it fails silently, on real financial data, in ways that look plausible until you check.

So this skill only auto-writes a category when the evidence is hard, and reads item text itself instead of pattern-matching it:

- **Tier 1 (write it):**
  - A `find-amazon-transactions` match with a real order number and parseable item text. Read the item description yourself and pick the category that fits the actual product — don't apply keyword rules, and for multi-item orders, categorize by the primary/first item listed.
  - A `find-payee-transactions` result with **at least 3 prior transactions** and a `most_common_category` that isn't itself "Uncategorized." Fewer transactions, or a majority category of "Uncategorized," isn't a real signal — it just means there's no history yet.
- **Tier 2/3 (leave it, explain why):** general knowledge about a merchant with no YNAB-side evidence (e.g. "this is probably a grocery store"), ambiguous Amazon matches (multiple orders tie on amount/date), unmatched transactions, or genuinely no data (a paper check with no payee or memo). These are real, useful observations — report them in the needs-review list with your reasoning, just don't write them.

## Workflow

### Step 1 — Resolve the budget and snapshot the safety baseline

Resolve `budget_id` (ask via `AskUserQuestion` if it's ambiguous or nothing's configured). Before touching anything else, run:

```bash
uv run python .agents/skills/categorize-unapproved-transactions/scripts/check_no_approvals.py \
  snapshot <snapshot-file> --budget-id <budget-id>
```

Pick a `<snapshot-file>` path in a scratch/temp location — this file only needs to survive for the rest of this run. This has to happen before any other reads or writes: it's the "before" picture the final safety check compares against, and it needs to be taken before anything about the budget has changed.

### Step 2 — Pull the data

Call `list-transactions` for the budget and `list-categories`. `list-transactions` on a real budget can return a very large result — if the tool's response gets truncated to a file, use `jq` (via `Bash`) to filter and extract rather than trying to read the raw JSON directly; the tool's own error message tells you how. Filter to `approved == false && deleted == false` — that's the working set for the rest of this skill.

### Step 3 — Trust the raw bank descriptor, not the YNAB payee name

For every transaction, look at `import_payee_name_original`, not `payee_name`, when figuring out who the real merchant was. YNAB's payee-matching can silently merge unrelated real-world merchants under one payee name — a prior run found a doctor's office charge and a separate credit-card payment both merged into unrelated Amazon-ish and "Link.com Cash back" payees respectively, purely because of coincidental substring matching in YNAB's auto-rename rules. `import_payee_name_original` is the actual, un-mangled string the bank reported; use it to group transactions by real merchant identity, and if you find a mismatch like this, note it separately in your output as a data-quality finding — it's useful information beyond just this run's categorization.

### Step 4 — Gather evidence

Call `find-amazon-transactions` **once** for the whole date range covered by the unapproved set (not once per transaction — it already does its own matching across the full set in one call). For payees you need historical pattern data on, call `find-payee-transactions` **one at a time, sequentially** — not in parallel. This YNAB server has retry/backoff for transient rate-limit errors, but avoiding an unnecessary burst of simultaneous calls is still cheaper than retrying through a rate limit you didn't need to hit.

### Step 5 — Classify

For each unapproved transaction, sort it into:

- **Tier 1**, per the evidence rules above — this is what step 6 will write.
- **Needs review** — general-knowledge guesses, ambiguous or unmatched Amazon results, or genuinely no data. Record your reasoning for each; even an unconfident guess is useful context for a human, as long as it's labeled as unconfident.
- **Internal transfer** — identified either by YNAB's own `transfer_account_id` field, or by the pattern of a matching amount on a nearby date across two of the user's own tracked accounts (e.g. a same-day, same-amount movement between a checking and a savings account both present in this budget). No category applies to a transfer; note it separately and never write anything for it.

### Step 6 — Write tier-1 categories

Issue **one** batched `bulk-manage-transactions` call containing an `update` operation for every tier-1 transaction, each setting `category_id` to your chosen category. Also set `memo` to a short evidence trail, e.g. `"Auto-categorized: Amazon order #113-xxx — Hefty Storage Bags"` or `"Auto-categorized: historical pattern (12/15 prior transactions -> Medical)"` — this makes the reasoning visible inside YNAB itself later, not just in this conversation, which matters since a human reviewing the budget in a month won't have this chat transcript. Never include `approved` in any operation, for any transaction, under any circumstance.

If the batched call partially fails, report exactly which transaction IDs succeeded and which didn't, with the real error for the failures — never report full success when some writes didn't land.

### Step 7 — Verify nothing got approved

Run:

```bash
uv run python .agents/skills/categorize-unapproved-transactions/scripts/check_no_approvals.py \
  verify <snapshot-file>
```

This re-fetches the budget's current unapproved set and checks that every transaction ID present in the snapshot is still present now — not just that the *count* looks right (a bare count comparison can hide the exact bug this exists to catch: some transactions could be wrongly approved while unrelated new ones arrive from a bank sync in the same window, and the count alone would look unchanged). This check runs as a real subprocess independent of anything the skill does or says about itself — treat a non-zero exit as a hard failure. Report it prominently, with the exact transaction IDs the script prints, and do not describe the run as successful.

### Step 8 — Report

Produce a structured summary — counts written vs. needs-review (grouped by category and by reason), the needs-review list itself with reasoning, any payee data-quality mismatches found in step 3, and the step 7 safety-check result — plus a human-readable version of the same for the chat. The structured form is meant to be consumable by a future trend-analysis pass over the same month; keep field names stable if you're asked to run this repeatedly.

## Bundled script

`scripts/check_no_approvals.py` — talks to the YNAB API directly (via this repo's own `ynab_mcp.client`/`ynab_mcp.config`, same `YNAB_PAT`), independent of any MCP tool call. Two subcommands, both used above: `snapshot <file> --budget-id <id>` and `verify <file>`. Run it with `uv run python` from the repository root so it picks up the project's installed dependencies.
