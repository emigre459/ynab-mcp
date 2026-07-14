# Changelog

## 2026-07-14
- feat: add transaction & budget write tools (#12) — four new MCP tools
  gated by `YNAB_READ_ONLY`: `bulk-manage-transactions` (best-effort batch
  create/update/delete, esp. `category_id` changes), `manage-budgeted-amount`
  (assign or move budgeted amounts between categories, with rollback on
  partial move failure), `manage-payees` (rename/merge), and
  `manage-scheduled-transaction` (create/update/delete a recurring
  transaction). All four are always registered; a shared
  `client.require_writable` guard blocks execution (not discovery) when
  read-only. Verified live against a real YNAB budget, which surfaced and
  fixed a real bug in the `ynab` PyPI SDK's `update_transactions` response
  handling (reported upstream:
  [ynab/ynab-sdk-python#33](https://github.com/ynab/ynab-sdk-python/issues/33)).

## 2026-07-12
- chore: initialize from agentic-ai-powered-repo template
- feat: add core YNAB MCP server foundation (#11) — a FastMCP v3 stdio
  server exposing read-only YNAB data (`list-budgets`, `list-accounts`,
  `list-categories`, `list-transactions`, `get-month-info`, `list-payees`,
  `lookup-entity-by-id`), backed by the official `ynab` PyPI client and
  registered in `.mcp.json` for use from Claude Code
