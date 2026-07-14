# Changelog

## 2026-07-13
- feat: add `flag-category-spend` and `analyze-category-trends` MCP tools
  (#13) — single-month overspend/underspend flagging against a
  configurable percentage threshold, and multi-month trend detection for
  a category whose budget keeps rising while still overspent
  (`rising_overspend`) or a category persistently underspent
  (`persistent_underspend`), using a majority-of-months rule so a single
  anomalous month doesn't trigger a false flag
- feat: add `find-payee-transactions` MCP tool (#14) — payee/transaction
  pattern lookup with exact/substring/fuzzy payee matching (handling
  inconsistent YNAB payee naming like "AMZN Mktp" vs "Amazon.com"),
  per-payee stats (transaction count, typical amount, amount range, most
  common category), and a recurring-charge heuristic

## 2026-07-12
- chore: initialize from agentic-ai-powered-repo template
- feat: add core YNAB MCP server foundation (#11) — a FastMCP v3 stdio
  server exposing read-only YNAB data (`list-budgets`, `list-accounts`,
  `list-categories`, `list-transactions`, `get-month-info`, `list-payees`,
  `lookup-entity-by-id`), backed by the official `ynab` PyPI client and
  registered in `.mcp.json` for use from Claude Code
