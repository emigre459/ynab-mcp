# Changelog

## 2026-08-01
- feat: add retry/backoff for transient YNAB API failures (#17) — a shared
  `call_with_retry` helper (via `tenacity`) wraps every direct YNAB SDK call
  across all 12 tool modules, retrying 429s (rate limit) and 5xxs with
  exponential backoff, capped at 3 attempts. The two non-idempotent
  create-only call sites (`bulk-manage-transactions`'s create group,
  `manage-scheduled-transaction`'s create) retry 429 only, never 5xx, to
  avoid risking a duplicate real transaction on an ambiguous server error.
  `errors.py` now appends rate-limit context and retry-timing guidance to a
  429's message once retries are exhausted, so a calling agent can inform
  the user rather than surfacing YNAB's raw "Too many requests".
- fix: batch `find-payee-transactions` into a single `list-transactions`
  call instead of one per matched payee (#17) — this N+1 pattern was the
  original trigger for the retry/backoff work above. New optional
  `since_date`/`until_date` parameters let a caller narrow the fetch window
  for budgets with heavy transaction volume.

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
