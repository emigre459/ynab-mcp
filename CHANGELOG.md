# Changelog

## 2026-07-14
- feat: add find-amazon-transactions matching tool (#15) — matches YNAB
  transactions against real Amazon order/transaction history (via the
  `amazon-orders` PyPI library) and proposes categorizations with
  confidence/reasoning (exact/near-date/split-shipment/ambiguous), without
  writing anything back to YNAB. Registered only when Amazon credentials
  are configured and a session can be established (fail-soft); a one-time
  `scripts/amazon_login.py` establishes that session, including automatic
  handling of Amazon's JavaScript bot-detection challenges via a headless
  browser. `include_approved` (default off) keeps results focused on
  transactions still needing review.

## 2026-07-12
- chore: initialize from agentic-ai-powered-repo template
- feat: add core YNAB MCP server foundation (#11) — a FastMCP v3 stdio
  server exposing read-only YNAB data (`list-budgets`, `list-accounts`,
  `list-categories`, `list-transactions`, `get-month-info`, `list-payees`,
  `lookup-entity-by-id`), backed by the official `ynab` PyPI client and
  registered in `.mcp.json` for use from Claude Code
