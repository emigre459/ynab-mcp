# ynab-mcp

MCP server for YNAB

Python backend managed with `uv`. Run `make deps` then `make pr_check`.

## Setup

1. Copy `.env.example` to `.env` and set `YNAB_PAT` to a YNAB personal
   access token (https://api.ynab.com/#personal-access-tokens).
2. Optionally set `YNAB_DEFAULT_BUDGET_ID` to skip passing a budget id to
   every tool call (this also hides the `list-budgets` tool, since there's
   only one budget context).
3. To use this server from Claude Code, copy `.mcp.json.example` to
   `.mcp.json` and set the `--directory` arg to this repo's absolute path
   on your machine (`.mcp.json` is gitignored — it's machine-specific).

## Running

```bash
make run
# or equivalently:
uv run ynab-mcp
```

This starts the MCP server over stdio. To exercise it with
[MCP Inspector](https://github.com/modelcontextprotocol/inspector):

```bash
npx @modelcontextprotocol/inspector uv run ynab-mcp
```

In the Inspector UI: click **Connect**, then **List Tools** — you should
see all 9 tools listed in [Tools](#tools) below (or 8, with `list-budgets`
hidden, if you set `YNAB_DEFAULT_BUDGET_ID`). Run `list-budgets` (or
`list-accounts` with a `budget_id`) and confirm it returns your real YNAB
data, not an error.

## Tools

Read-only tools, backed by the official `ynab` PyPI client:

- `list-budgets` — every budget the token can access (hidden when
  `YNAB_DEFAULT_BUDGET_ID` is set).
- `list-accounts`, `list-categories`, `list-payees` — enumerate entities in
  a budget.
- `list-transactions` — filterable by account, category, payee, and/or
  date range.
- `get-month-info` — budget totals and category detail for a month.
- `lookup-entity-by-id` — fetch a single account/category/payee/
  transaction/month by id.
- `flag-category-spend` — flag categories over/under budget by more than a
  configurable `threshold` (default 10%) for a single month.
- `analyze-category-trends` — walk a trailing window of months
  (`months`, default 6) per category and flag a rising budget that's still
  overspent (`rising_overspend`) or a category persistently underspent
  (`persistent_underspend`), using a majority-of-months rule so one
  anomalous month doesn't trigger a false flag.

Write/mutation tools are out of scope for this server (a follow-up card).

### Testing the spend-analysis tools against real data

`flag-category-spend` and `analyze-category-trends` are only meaningfully
verified against a real budget's spending history — unit tests cover the
logic, but not whether it matches what you actually know about your
budget. Via MCP Inspector (or any MCP client pointed at `uv run ynab-mcp`):

1. Call `flag-category-spend` with `month="current"` (or a past month you
   remember overspending in). Confirm the flagged categories and their
   `reason` text match what you know actually happened that month.
2. Call it again with a much higher `threshold` (e.g. `0.99`) and confirm
   fewer/no categories are flagged — sanity-checks the threshold is
   actually applied.
3. Call `analyze-category-trends` with defaults. Confirm any category you
   know has had its budget repeatedly raised while still running over
   shows up as `rising_overspend`, and any category you know sits mostly
   unused shows up as `persistent_underspend`.
4. A category with a genuine one-off anomalous month (e.g. a single large
   purchase) should NOT appear in `analyze-category-trends`'s output
   unless it's a recurring pattern — that's the majority-of-months rule
   working as intended.
