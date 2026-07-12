# Core YNAB MCP Server Foundation — Design

- **Issue:** [#11](https://github.com/emigre459/ynab-mcp/issues/11) — Core YNAB MCP server foundation
- **Parent epic:** [#10](https://github.com/emigre459/ynab-mcp/issues/10) — AI-driven budget coaching & categorization for parents' YNAB budget
- **Date:** 2026-07-12

## Why

Every other child of epic #10 (write tools, overspend/underspend flagging, payee lookup,
Amazon-transaction matching) needs a modern, working stdio MCP server exposing core YNAB
read data. The reference implementation ([Jtewen/ynab-mcp](https://github.com/Jtewen/ynab-mcp))
targets a stale `mcp`-bundled FastMCP API, not the current `fastmcp` v3 package. This card
builds that foundation from scratch.

## Terminology note: Budget vs Plan

The official `ynab` PyPI client (v4.2.0, latest as of this writing) renamed "Budget" to
"Plan" throughout its generated API surface: `BudgetsApi` no longer exists (it's
`PlansApi`), and every method takes `plan_id` instead of `budget_id`. This was confirmed
by introspecting the installed `ynab==4.2.0` package directly (Context7's docs mixed old
and new terminology inconsistently, so they weren't trustworthy on their own for this
point).

YNAB's actual product UI still calls it "Budget" everywhere, and issue #11's acceptance
criteria explicitly name `YNAB_DEFAULT_BUDGET_ID` and a `list-budgets` tool. **Decision:**
our public surface (env vars, tool names, parameter names, docstrings) uses "budget"
terminology throughout, matching the product and the issue text. The `budget_id` →
`plan_id` translation happens in exactly one place (`client.py`) when calling into the
`ynab` SDK.

## Module layout

```
src/ynab_mcp/
  __init__.py
  config.py        # Settings: YNAB_PAT, YNAB_DEFAULT_BUDGET_ID, YNAB_READ_ONLY
  client.py         # ApiClient factory/context manager from Settings; budget_id -> plan_id translation
  errors.py         # ApiException -> ToolError translation helper
  server.py         # FastMCP instance, tool registration, mcp.run()
  tools/
    __init__.py
    budgets.py       # list-budgets (registered only if no default budget configured)
    accounts.py       # list-accounts
    categories.py     # list-categories
    transactions.py    # list-transactions (filterable)
    payees.py         # list-payees
    months.py          # get-month-info
    lookup.py          # lookup-entity-by-id
```

This replaces the template placeholder `src/example_app/` (and its `tests/test_greeting.py`
counterpart). `pyproject.toml`'s `[tool.uv.build-backend] module-name` is updated from
`example_app` to `ynab_mcp`, and the stale comment referencing the now-deleted
`scripts/init_template.py` is removed.

## Config (`config.py`)

A `Settings` dataclass (or Pydantic model — implementation detail for the plan) built from
`os.environ` after `load_dotenv()` (per `.agents/rules/python/load-dotenv-first.md`):

- `ynab_pat: str` — **required**. Missing or empty raises a clear error immediately at
  server startup (fail-hard-not-warn), not on first tool call.
- `ynab_default_budget_id: str | None` — optional.
- `ynab_read_only: bool` — parsed from `YNAB_READ_ONLY`, **defaults to `True`** when unset.
  Currently **read but not enforced** — no write tools exist in this card (they're epic
  #10's child 2, "gated by `YNAB_READ_ONLY`"). This card only wires the config surface the
  issue's acceptance criteria require.

## Client (`client.py`)

One `ynab.ApiClient` is constructed at server startup from `Settings.ynab_pat` and reused
for the process lifetime (matches FastMCP's stdio lifespan pattern: expensive init
completes before transport I/O begins). A small helper resolves our public `budget_id`
into the SDK's `plan_id` parameter — this is the **only** place that translation happens.

A `resolve_budget_id(budget_id: str | None, settings: Settings) -> str` helper backs every
tool except `list-budgets`: if `budget_id` is omitted, falls back to
`settings.ynab_default_budget_id`; raises `ToolError` if neither is available.

## Tool surface

All tools other than `list-budgets` take an **optional** `budget_id: str | None`
parameter resolved via `resolve_budget_id`. Signatures are uniform regardless of whether a
default budget is configured (simplest for the calling agent and for testing).

| Tool | Parameters | Notes |
|------|-----------|-------|
| `list-budgets` | *(none)* | Registered **only** when `Settings.ynab_default_budget_id` is unset (`fastmcp`'s `on_duplicate_tools`/conditional registration is plain Python — the `@mcp.tool` call is simply skipped). |
| `list-accounts` | `budget_id?` | Wraps `AccountsApi.get_accounts`. |
| `list-categories` | `budget_id?` | Wraps `CategoriesApi.get_categories`. |
| `list-transactions` | `budget_id?`, `account_id?`, `category_id?`, `payee_id?`, `since_date?`, `until_date?` | The SDK exposes one entity filter per endpoint (`get_transactions_by_account` / `_by_category` / `_by_payee`), not combinable server-side. Dispatch on **at most one** of `account_id`/`category_id`/`payee_id` — raise `ToolError` if more than one is given. `since_date`/`until_date` are supported uniformly across all four endpoints and always apply; with no entity filter set, dispatches to plain `get_transactions` (date-filtered only). |
| `get-month-info` | `budget_id?`, `month` | Wraps `MonthsApi.get_plan_month`. `month` accepts ISO date or `"current"` per the SDK. |
| `list-payees` | `budget_id?` | Wraps `PayeesApi.get_payees`. |
| `lookup-entity-by-id` | `entity_type: Literal["account","category","payee","transaction","month"]`, `id`, `budget_id?` | Generic resolver — dispatches to the matching single-item getter (`get_account_by_id`, `get_category_by_id`, `get_payee_by_id`, `get_transaction_by_id`; `month` dispatches to `get_plan_month` treating `id` as the month value). Useful when an agent has a bare ID (e.g. a transaction's `category_id`) and needs the full object without knowing which list to search. |

## Error handling (`errors.py`)

A single helper (e.g. `@translate_ynab_errors` decorator or explicit `try/except` wrapper)
catches `ynab.rest.ApiException`, extracts YNAB's `detail`/`message` from the response
body, and raises `fastmcp.exceptions.ToolError(detail)`. `ToolError` messages are **always**
sent to the client, never masked — the agent needs the real reason (bad token, unknown
budget, rate limit) to react usefully. Every tool wrapper routes through this helper so the
mapping is written once, not duplicated per tool.

## Testing

- Each `tools/*.py` module's plain function (the part that isn't the thin `@mcp.tool`
  wrapper) is unit-tested directly with a mocked `ynab.*Api` instance (`pytest-mock`),
  covering: the success path, and an `ApiException` path asserting it surfaces as
  `ToolError` with the expected message.
- `config.py`: missing-`YNAB_PAT` failure, `YNAB_READ_ONLY` default-parsing.
- `client.py`: `resolve_budget_id` — explicit id wins, falls back to default, raises when
  neither present.
- No FastMCP-protocol-level integration test is required for unit coverage — that's
  build-from-issue's Step 6 (project E2E), exercised via MCP Inspector or `fastmcp`'s
  in-memory test client.
- Coverage gate: `make coverage` (80%, per repo default).

## Out of scope (per issue text)

- Write/mutation tools (categorization, budgeted-amount changes, payee-merge, scheduled
  transactions) — epic #10 child 2, gated by `YNAB_READ_ONLY` when built.
- Enforcing `YNAB_READ_ONLY` — read/parsed now, enforced when write tools exist.
