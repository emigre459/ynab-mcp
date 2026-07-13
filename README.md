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
see all 7 tools listed in [Tools](#tools) below (or 6, with `list-budgets`
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

Write/mutation tools are out of scope for this server (a follow-up card).
