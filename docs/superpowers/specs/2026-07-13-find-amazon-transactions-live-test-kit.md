# Live test kit — find-amazon-transactions (issue #15)

Everything below runs from this worktree: `/Users/davemcrench/Projects/ynab-mcp/.claude/worktrees/15-amazon-transactions`

## 1. Configure credentials

```bash
cp .env.example .env   # skip if you already have one
```

Edit `.env` and set:
- `YNAB_PAT` — your real YNAB personal access token (if not already set)
- `YNAB_DEFAULT_BUDGET_ID` — your real budget id (optional, but saves passing `budget_id` every call)
- `AMAZON_USERNAME` / `AMAZON_PASSWORD` — your real Amazon login
- `AMAZON_OTP_SECRET_KEY` — only if your Amazon account uses OTP-based 2FA (the TOTP secret, not a one-time code)

## 2. One-time Amazon login

```bash
uv run python scripts/amazon_login.py
```

This may prompt interactively (password confirmation, a CAPTCHA, an SMS/app 2FA code) — that's expected and is exactly why this step is separate from the tool itself. On success it prints `Amazon login succeeded; session persisted for the MCP server to reuse.` You should not need to run this again unless the session later expires (the tool will tell you to re-run this if so).

## 3. Start the server and connect MCP Inspector

```bash
npx @modelcontextprotocol/inspector uv run ynab-mcp
```

This opens a browser UI. Click **Connect**, then **List Tools** — confirm `find-amazon-transactions` appears in the list alongside the other 7 read-only tools.

## 4. Call the tool

Select `find-amazon-transactions` in the Inspector, and run it with:
- `budget_id` — omit if `YNAB_DEFAULT_BUDGET_ID` is set in `.env`, otherwise pass your real budget id
- `since_date` — pick a date a few months back, e.g. `"2026-04-01"`, so the call has a bounded, fast YNAB fetch
- leave `until_date` and `date_window_days` at their defaults

## 5. What "works" looks like

- The response has three keys: `matches`, `ambiguous`, `unmatched`.
- **`matches`**: each entry should correspond to a real Amazon order you recognize — check that `reasoning` mentions plausible item titles, that `classification` (`exact`/`near-date`/`split-shipment`) makes sense for that charge, and that `amazon_transaction.grand_total` matches what you'd expect for that YNAB transaction's amount (same magnitude, correct sign — negative for a purchase).
- **`ambiguous`**: any entries here should be genuinely ambiguous to *you* too (e.g. two same-amount Amazon charges close in date) — not a case where the right answer was obvious and the tool just missed it.
- **`unmatched`**: Amazon-payee YNAB transactions with no found Amazon charge — reasonable if that transaction is older than Amazon's own transaction-history retention, or it's a subscription/digital charge not in your order history.

## 6. Pass/fail criterion

**Pass**: at least a few real Amazon orders from your `since_date` window show up correctly in `matches`, with sane reasoning and correct-sign amounts. Nothing in `matches` is obviously wrong (wrong order paired with a transaction, backwards sign, nonsense reasoning).

**Fail indicators and what to check:**
- Every result lands in `unmatched`, none in `matches` → check `amazon_transaction.grand_total`'s sign relative to `ynab_transaction.amount` if you can see both (should both be negative for a purchase); this was a bug we already found and fixed once, so worth confirming for real data.
- Tool call raises an error mentioning `scripts/amazon_login.py` → the Amazon session expired or never got established; rerun step 2.
- `find-amazon-transactions` doesn't appear in the tool list at all → `.env`'s `AMAZON_USERNAME`/`AMAZON_PASSWORD` aren't set or aren't being picked up; double check step 1.

Report back what you see — especially anything under "Fail indicators."
