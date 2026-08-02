# Live test kit — parallelize Amazon enrichment fetches (issue #20)

Everything below runs from this worktree: `/Users/davemcrench/Projects/ynab-mcp/.worktrees/20-parallelize-amazon-enrichment-fetches`

## What this proves that automated tests can't

This is a pure performance fix -- `find-amazon-transactions`' output shape and matching behavior are unchanged (proven by 205 passing unit/integration tests, all mocked). What's left is the part only a real Amazon session can prove: that the concurrent enrichment fetches actually run against the real, unofficial HTML-scraping site correctly and faster, without tripping bot-detection.

## 1. Configure credentials

```bash
cp .env.example .env   # skip if you already have one
```

Edit `.env` and confirm these are set (should already be, from earlier #15 testing):
- `YNAB_PAT` / `YNAB_DEFAULT_BUDGET_ID`
- `AMAZON_USERNAME` / `AMAZON_PASSWORD` (`AMAZON_OTP_SECRET_KEY` if your account uses OTP 2FA)

If your persisted Amazon session has expired, re-run `uv run python scripts/amazon_login.py` first.

## 2. Start the server and connect MCP Inspector

```bash
npx @modelcontextprotocol/inspector uv run ynab-mcp
```

Click **Connect**, then **List Tools** -- confirm `find-amazon-transactions` appears (15 tools total, matching what you saw for #17's kit, since Amazon credentials are configured).

## 3. Call the tool with a real, meaningfully-sized window

Pick a `since_date` far back enough to pull in a decent number of distinct Amazon orders -- the whole point of this fix is the win on *many* distinct orders, so a window with only 1-2 matches won't show much. If you have a `since_date` from earlier testing that produced ~10+ matches, reuse it; otherwise try something like 3-6 months back.

- `budget_id` -- omit if `YNAB_DEFAULT_BUDGET_ID` is set
- `since_date` -- e.g. `"2026-02-01"`
- leave `until_date`/`date_window_days`/`include_approved` at defaults

**Note the wall-clock time** the call takes (Inspector shows request duration, or just eyeball it).

## 4. What "works" looks like

- **Correctness unchanged**: same checks as #15's original kit -- each entry in `matches` should correspond to a real Amazon order you recognize, `reasoning` should mention plausible item titles, `classification` should make sense, `amazon_transaction.grand_total` should match the YNAB transaction's amount (same magnitude, negative sign for a purchase). Nothing about *what* comes back should look different from before this branch.
- **Speed**: if your window has a good number of distinct matched orders (say 10+), the call should feel noticeably faster than a strictly-sequential fetch would -- issue #20 was born from a real ~47-match run that took multiple minutes; with 3-way concurrency that same run should be roughly in the neighborhood of 1/3 the wall-clock time (not exact, since fetch times vary, but a clear, not marginal, difference).
- **No new errors**: no auth failures, no bot-detection/CAPTCHA errors that weren't happening before. Up to 3 near-simultaneous logins now fire on a call with distinct enrichment fetches across worker threads (each worker builds its own session on first use) -- if you see anything Amazon-side that looks like rate-limiting or a fresh challenge, that's worth reporting even though it wasn't explicitly predicted.

## 5. Pass/fail criterion

**Pass**: matches/reasoning/amounts look correct (same bar as #15's kit), and a run with a meaningful number of distinct orders is clearly faster than your recollection of pre-#20 runs (or than a rough mental "N orders × a few seconds each" sequential estimate).

**Fail indicators and what to check:**
- Results look wrong (wrong item titles, wrong amounts, missing matches) → likely NOT this branch's fault (matching logic untouched), but worth double-checking against a `main`-branch run if you have doubts.
- No speedup at all on a large match set → check whether your window actually produced many *distinct* orders (repeats within one order don't count -- the old code already deduped those for free).
- Any Amazon-side auth/challenge error → note whether it happened once or repeatedly; a one-off is more likely incidental, repeated failures on every run would be a real concern worth flagging back for further investigation.

Report back what you see -- especially timing (even a rough "felt like Xs instead of Ys") and anything under "Fail indicators."
