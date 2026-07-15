# Live test kit — retry/backoff + payee-lookup N+1 fix (issue #17)

Everything below runs from this worktree: `/Users/davemcrench/Projects/ynab-mcp/.worktrees/17-retry-backoff-ynab-api`

## What this does and doesn't prove

This is a **regression check**, not a retry-trigger test. Deliberately forcing a real 429 against your actual YNAB token would burn your hourly 200-request quota for up to an hour — not worth it just to watch a retry happen. The retry logic itself is already proven two ways that don't touch your real account:
- 199 unit tests mock `ynab.ApiException` directly and verify `call_with_retry`'s behavior (429/5xx retry policy, the `include_5xx=False` safety asymmetry on the two non-idempotent create call sites, retry exhaustion).
- A new integration test (`make integration`) points the real `ynab` SDK at a local mock HTTP server that returns 429-then-200, proving the real SDK + tenacity stack retries correctly — no live YNAB API involved.

What's left to check here is the part only your real budget can prove: that wrapping every call site with retry logic, and rebuilding `find-payee-transactions` to batch its API calls, **didn't change what any tool actually returns**.

## 1. Configure credentials

```bash
cp .env.example .env   # skip if you already have one
```

Edit `.env` and set:
- `YNAB_PAT` — your real YNAB personal access token (if not already set)
- `YNAB_DEFAULT_BUDGET_ID` — your real budget id (optional, saves passing `budget_id` every call)

## 2. Start the server and connect MCP Inspector

```bash
npx @modelcontextprotocol/inspector uv run ynab-mcp
```

Click **Connect**, then **List Tools** — confirm all 14 tools appear (unchanged from before this issue; retry wrapping added no new tools).

## 3. Read-only regression checks

Run each of these and just confirm the response looks like real data from your budget (right accounts, right categories, right transactions) — nothing should look different from before this branch:

- **`list-accounts`** — no params needed.
- **`list-categories`** — no params needed.
- **`get-month-info`** with `month: "current"`.
- **`lookup-entity-by-id`** with `entity_type: "account"` and a real `entity_id` from your `list-accounts` result.

## 4. `find-payee-transactions` — the N+1 fix

This is the one with an actual behavior-adjacent change (batched into one API call instead of one-per-matched-payee), so check it more closely:

- Pick a payee query that matches **multiple** payees in your budget if you can (e.g. a common merchant name with a couple of naming variants) — `"amazon"` or similar.
- Call `find-payee-transactions` with just `payee_query` set (leave `since_date`/`until_date` unset).
- Confirm: each matched payee shows up as its **own separate group** (not pooled together), with a sensible `transaction_count`, `typical_amount`, and `most_common_category` for each.
- Then call it again with `since_date` set to a few months back (e.g. `"2026-04-01"`) — confirm `transaction_count` for each group drops or stays the same (never increases), consistent with narrowing the window.

## 5. Pass/fail criterion

**Pass:** every tool above returns data that matches what you see in the real YNAB app for your budget — right accounts, right transaction counts, right categories, no missing or duplicated groups in `find-payee-transactions`.

**Fail indicators and what to check:**
- `find-payee-transactions` returns **fewer groups** than before, or pools two distinct payees into one — check whether the grouping-by-`payee_id` logic is matching the wrong payee (a payee_id mismatch would silently drop or merge groups).
- `find-payee-transactions` returns **zero results** for a payee you know has transactions — check whether `since_date`/`until_date` are narrower than you intended (they default to YNAB's own ~1-year window when unset).
- Any tool call raises an unexpected error — check the error message; if it mentions "rate limit exceeded," that's the enriched 429 message working as intended (see below), not a bug.

## 6. Optional: confirm the enriched 429 message reads sensibly (no live trigger needed)

You don't need to trigger a real 429 to see the new message — just read it: `src/ynab_mcp/errors.py`'s `translate_api_exception` now appends rate-limit context and retry-timing guidance whenever a 429 exhausts its retries. If you happen to hit one naturally during other testing, confirm the message is genuinely more useful than YNAB's raw `"Too many requests"` — it should mention the 200/hour rolling window and suggest waiting about an hour.

Report back what you see — especially anything under "Fail indicators."
