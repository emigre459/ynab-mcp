---
name: analyze-budget-trends
description: Analyzes a YNAB budget's spending trends for a target month -- aggregating flag-category-spend and analyze-category-trends into budget successes and failures, proposing next-month budgeted-amount changes (suggestions only, never applied), and assembling a "Lingering Questions" list of anomalies (including duplicate/overlapping subscriptions detected by comparing per-payee charge cadence against real-world vendor pricing). Use this whenever the user wants a monthly budget review, wants to know which categories are over/under budget, asks about spending trends or patterns, wants help deciding next month's budgeted amounts, or suspects they're being double-billed for something -- triggers on /analyze-budget-trends as well as natural language like "how did we do on the budget this month," "run the monthly trend analysis," or "am I paying for two subscriptions to the same thing."
allowed-tools: mcp__ynab__list-transactions mcp__ynab__flag-category-spend mcp__ynab__analyze-category-trends mcp__ynab__find-payee-transactions WebSearch AskUserQuestion Bash
---

# Analyze Budget Trends

## Overview

Raw over/under-spend numbers aren't a review-ready story. This skill turns a month of YNAB category data into three things a human can actually act on: what's going well, what's going badly (and what to maybe do about it), and a short list of things worth asking about — each with at least one real explanation attached, never a bare "this looks weird."

**Announce at start:** "Using the analyze-budget-trends skill to analyze this month's budget."

## Dependency on categorization

This skill assumes `categorize-unapproved-transactions` has already run for the target month — category totals need to be settled before trend numbers mean anything, since an unapproved pile of miscategorized transactions will skew both the successes/failures buckets and the trend window. Nothing in this skill enforces that ordering (that's the job of a monthly orchestrator this skill doesn't own yet); if you have reason to think categorization hasn't run recently for this budget, say so before presenting results, so the numbers aren't taken as more final than they are.

## Workflow

### Step 1 — Resolve budget and target month

Resolve `budget_id`. Resolve the target month: default to `"current"`, but this skill must work against an arbitrary past month too — a monthly review triggered on the 1st is analyzing the month that *just* closed, not the one that just started. Accept an ISO month (`"2026-07-01"`) or `"current"`, matching what `flag-category-spend`/`analyze-category-trends` already expect.

### Step 2 — Successes and failures

Call `flag-category-spend` for the target month and `analyze-category-trends` with `end_month` set to the target month. Bucket categories into:

- **Successes** — tracking within threshold, or trending in a healthy direction.
- **Failures** — flagged by either tool: single-month overspend, or a multi-month pattern (`analyze-category-trends` only counts something a real trend once it recurs across a majority of the trailing window — that's the tool's own `majority_ratio` guard against calling one bad month a "pattern").

### Step 3 — Suggested changes (proposals only)

For each failure, propose a next-month budgeted-amount change with a one-line rationale — e.g. "Groceries has overspent 4 of the last 6 months by ~$80; consider raising the budgeted amount by $75-100." **Never** call anything that writes this back to YNAB. The suggestion is the deliverable; applying it is the user's call.

### Step 4 — Subscription-cadence detection

Some of the most useful findings here don't come from category totals at all — they come from noticing a single payee is being charged more often than its own billing model allows. A prior run of this workflow found exactly this: Lumosity (a $18.95/month cognitive-training app) was being charged 7 times in about 2 months, and FuboTV was billing roughly every 2 weeks instead of monthly, with two different dollar amounts alternating. Both turned out to look like duplicate/overlapping subscriptions rather than one subscription billing incorrectly. That's the pattern to look for:

1. For payees that look recurring (roughly-similar amounts appearing repeatedly across the trailing window), pull their **full** transaction history — `find-payee-transactions` for the summary, `list-transactions` filtered by `payee_id` for the actual dates and amounts.
2. Compute the day-gap between consecutive charges. A single healthy subscription should show one roughly-consistent period (weekly, monthly, etc.) — if you sort the charges by date and the gaps look irregular, check whether they actually decompose into **multiple overlapping cycles**: e.g. dates landing on the 11th, 15th, and 22nd of each month, each recurring independently, rather than one irregular monthly charge. That decomposition is the signal, not the raw irregularity.
3. Before flagging anything, use `WebSearch` to check the vendor's real billing frequency and price tiers. This matters in both directions: it can confirm a suspicion (Lumosity is documented as monthly-only, so 7 charges in 2 months has no legitimate explanation), and it can also *rule one out* (a charge that looks anomalously large might just be a legitimate top-tier plan plus a mandatory add-on fee — verify actual pricing before treating "the dollar amount looks weird" as evidence of a problem).
4. If the evidence holds up, add it to Lingering Questions with the specific dates/amounts and the pricing source you checked, so the user can verify quickly instead of re-deriving your reasoning.

### Step 5 — Assemble Lingering Questions

Combine into one list: anomalous one-off transactions (unusually large or out-of-pattern charges), still-uncategorized items handed off from `categorize-unapproved-transactions`'s needs-review output (if available), subscription-cadence findings from Step 4, and any other unexplained trend `analyze-category-trends` surfaced that doesn't fit neatly into Step 2's buckets. Every entry needs at least one plausible explanation — if you genuinely can't form one, that itself is worth saying explicitly rather than omitting the item.

### Step 6 — Report

Produce one structured report object — successes, failures, suggested changes, Lingering Questions — plus a human-readable chat rendering. Keep the structure's field names stable across runs; a future deck-building step is meant to consume this directly.
