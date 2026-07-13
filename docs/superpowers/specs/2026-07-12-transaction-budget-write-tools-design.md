# Transaction & Budget Write Tools — Design

- **Issue:** [#12 — Transaction & budget write tools](https://github.com/emigre459/ynab-mcp/issues/12)
- **Epic:** [#10 — AI-driven budget coaching & categorization for parents' YNAB budget](https://github.com/emigre459/ynab-mcp/issues/10)
- **Date:** 2026-07-12

## Why

Manual transaction categorization and budget tuning for the user's parents' YNAB budget is tedious to do by hand through the UI. Write tools let an agent apply those changes directly (with human review) instead of clicking through YNAB.

## Scope

Four new MCP tools, all gated by `YNAB_READ_ONLY`:

1. `bulk-manage-transactions` — create/update/delete multiple transactions in one call, primarily for bulk category_id changes.
2. `manage-budgeted-amount` — assign or move budgeted amounts between categories for a given month.
3. `manage-payees` — rename or merge payees.
4. `manage-scheduled-transaction` — create/update/delete a single recurring transaction.

Out of scope: category/account creation or editing, budget-level settings, anything not named above. Those may become future epic-#10 cards if needed.

## Architecture

Follows the established `src/ynab_mcp/tools/` pattern exactly (see `AGENTS.md`): each new tool group is its own module with a plain, testable function plus a thin `register(mcp, client, settings)` function that registers a `@mcp.tool`-decorated wrapper. New files:

- `src/ynab_mcp/tools/transactions_write.py` — `bulk-manage-transactions`
- `src/ynab_mcp/tools/budgeted_amount.py` — `manage-budgeted-amount`
- `src/ynab_mcp/tools/payees_write.py` — `manage-payees`
- `src/ynab_mcp/tools/scheduled_transactions.py` — `manage-scheduled-transaction`

All four are registered unconditionally in `server.py`'s `build_server()` — write tools are always discoverable in the MCP tool list, in both read-only and writable modes.

### Read-only guard

A new shared helper, `require_writable(settings: Settings) -> None`, added to `src/ynab_mcp/client.py` (alongside `resolve_budget_id`, which it's used next to in every write tool):

```python
def require_writable(settings: Settings) -> None:
    if settings.ynab_read_only:
        raise ToolError(
            "YNAB_READ_ONLY is enabled; write operations are disabled."
        )
```

Every write tool's plain function calls `require_writable(settings)` as its first statement, before constructing any YNAB API client call. This means the check is testable identically across all four tools (call the function, assert `ToolError`, assert the mocked `ynab.*Api` was never invoked) and requires no changes to `server.py`'s registration logic.

## Tool specs

### `bulk-manage-transactions`

**Parameters:** `operations: list[dict]`, `budget_id: str | None`.

Each operation dict has a required `action: Literal["create", "update", "delete"]`:

| action | required fields | optional fields |
|---|---|---|
| `create` | `account_id`, `date`, `amount` | `payee_id`, `payee_name`, `category_id`, `memo`, `cleared`, `approved`, `flag_color` |
| `update` | `id` | any of: `account_id`, `date`, `amount`, `payee_id`, `payee_name`, `category_id`, `memo`, `cleared`, `approved`, `flag_color` |
| `delete` | `id` | — |

**Behavior:** partition `operations` by `action`. Issue at most three physical YNAB API calls:
- All `create` items → one `TransactionsApi.create_transaction` call with a `PostTransactionsWrapper(transactions=[...])`.
- All `update` items → one `TransactionsApi.update_transactions` call with a `PatchTransactionsWrapper(transactions=[...])`.
- All `delete` items → a loop of `TransactionsApi.delete_transaction` calls (YNAB has no bulk-delete endpoint).

Each of the three groups is wrapped in its own try/except so a failure in one group (or one item within the delete loop) does not prevent the others from running. Returns a list of per-item results, in the same order as the input `operations`:

```python
{"action": "update", "id": "txn-1", "status": "ok", "detail": None}
{"action": "delete", "id": "txn-2", "status": "error", "detail": "Transaction not found"}
```

`detail` on error is the same message `translate_api_exception` would produce. The tool function itself only raises `ToolError` for: the read-only guard, an empty `operations` list, or a structurally invalid operation (missing `action`, or missing the action's required id/fields) — anything that's a caller bug rather than a YNAB-side failure.

**Note on `create`/`update` group failures:** if the single grouped `create_transaction` or `update_transactions` call itself raises (e.g. one bad `account_id` in a batch of 10 creates — YNAB validates the whole payload), every item in that group is marked `"status": "error"` with the same translated detail message, since the SDK does not report which specific array element failed.

### `manage-budgeted-amount`

**Parameters:** `operation: Literal["assign", "move"]`, `month: str`, `budget_id: str | None`, plus:
- `assign`: `category_id`, `amount` (milliunits, absolute value to set).
- `move`: `from_category_id`, `to_category_id`, `amount` (milliunits to shift).

`month` is parsed with the existing `parse_month` helper from `months.py` (ISO date or `"current"`).

**assign:** one `CategoriesApi.update_month_category` call setting `budgeted = amount`.

**move:**
1. `CategoriesApi.get_month_category_by_id` for `from_category_id` and `to_category_id` to read current `budgeted` values.
2. `update_month_category` on `from_category_id` with `budgeted = current - amount`.
3. `update_month_category` on `to_category_id` with `budgeted = current + amount`.

If step 3 fails: attempt a compensating call restoring `from_category_id`'s original `budgeted` value (step 2's pre-move value). Then raise a `ToolError`:
- If the rollback succeeded: `"Failed to move {amount} from {from_category_id} to {to_category_id} for {month}: {detail}. The source category was restored to its original budgeted amount."`
- If the rollback itself also failed: `"Failed to move {amount} from {from_category_id} to {to_category_id} for {month}: {detail}. Rollback of the source category also failed ({rollback_detail}) — {from_category_id} is left decremented by {amount} for {month} and needs manual correction."`

If step 1 or step 2 fails, no mutation has happened yet (step 1 is read-only, step 2 is the first write) — raise `ToolError` normally, no rollback needed.

### `manage-payees`

**Parameters:** `operation: Literal["rename", "merge"]`, `budget_id: str | None`, plus:
- `rename`: `payee_id`, `new_name`.
- `merge`: `source_payee_id`, `target_payee_id`.

**rename:** one `PayeesApi.update_payee` call setting `name = new_name`.

**merge:** `PayeesApi.get_payee_by_id(target_payee_id)` to read the target's current name, then `update_payee(source_payee_id, name=<target's name>)`. Setting a payee's name to exactly match an existing payee's name is YNAB's documented server-side merge trigger — no explicit delete call exists or is needed; YNAB retires the source payee automatically. Returns `{"merged_into": {"id": target_payee_id, "name": <name>}}`.

### `manage-scheduled-transaction`

**Parameters:** `operation: Literal["create", "update", "delete"]`, `budget_id: str | None`, plus:
- `create`: `account_id`, `date`, `amount`, `frequency`, plus optional `payee_id`, `payee_name`, `category_id`, `memo`, `flag_color`.
- `update`: `scheduled_transaction_id`, `account_id`, `date`, `amount`, `frequency`, plus optional `payee_id`, `payee_name`, `category_id`, `memo`, `flag_color`.
- `delete`: `scheduled_transaction_id`.

**Implementation note:** unlike `bulk-manage-transactions`' update (which is a YNAB PATCH — partial fields only), YNAB's scheduled-transaction update endpoint is a PUT: the SDK's `SaveScheduledTransaction` model requires `account_id` and `date` regardless of create vs. update, so `update` requires the same full field set as `create` (not "any subset" as originally drafted) — a caller must resupply the complete desired state, or fields omitted would be cleared server-side.

Each is a single, direct wrap of the corresponding `ScheduledTransactionsApi` method (`create_scheduled_transaction`, `update_scheduled_transaction`, `delete_scheduled_transaction`) — no batching, matching the issue's "a recurring transaction" (singular).

## Error handling

All YNAB `ApiException`s are translated via the existing `translate_api_exception` (unchanged). Read-only violations use the new `require_writable` guard (unchanged message format, one line, easy for a caller/agent to detect and explain to the human).

## Testing

One `tests/test_tools_<module>.py` per new module, mirroring the existing style (mock the relevant `ynab.*Api` class via `mocker.patch`, assert call arguments, assert `ApiException` → `ToolError` with the translated detail). Additive coverage beyond the existing pattern:

- **Read-only guard**, once per tool: `YNAB_READ_ONLY=true` → `ToolError` raised, mocked API never called; `YNAB_READ_ONLY=false` (or unset, since the default is `true` per `config.py`) → proceeds and calls the API normally.
- **`bulk-manage-transactions`**: mixed-batch test (one create, one update, one delete, all succeed); partial-failure test (one item fails, others still return `"status": "ok"`); malformed-operation test (missing `action`/`id` → `ToolError`, no API calls).
- **`manage-budgeted-amount` move**: happy path (two successful calls); second-call-failure-with-successful-rollback; second-call-failure-with-failed-rollback (asserts the specific error message naming the inconsistent state).
- **`manage-payees` merge**: asserts `get_payee_by_id` is called for the target before `update_payee` is called for the source, and that the source is renamed to the target's exact name.

## Migration notes

None — purely additive. No existing tool signatures or `server.py` registration logic change other than adding four new `register()` calls and importing `require_writable` into `client.py`.
