# Write-Tool Approval Prompt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every call to the four YNAB write tools shows a human a readable, name-based summary and writes only on an explicit yes.

**Architecture:** `approval.py` owns the protocol flow (era branch, single-use tokens, fingerprint, write-time re-check) and knows nothing about YNAB. `write_summaries.py` owns the YNAB side (names, current-state reads, prompt text). Each write closure becomes async and adds one `require_approval` call.

**Tech Stack:** FastMCP 4.1.4, MCP SDK 2.3 (`mcp_types`), `anyio.to_thread`, pytest + `fastmcp.Client`.

**Spec:** `docs/superpowers/specs/2026-11-01-write-approval-prompt-design.md`

## Global Constraints

- Closure gate order: `require_writable` → `resolve_budget_id` → field validation → `require_approval` → write.
- `YNAB_REQUIRE_WRITE_APPROVAL` defaults true; falsy set `false`/`0`/`no`. No per-call bypass parameter.
- Approved means `action == "accept"` and `content["value"] is True`, nothing looser.
- Every "not applied" outcome is a raised `ToolError`, never a success result.
- Every direct YNAB read uses `call_with_retry` or an already-wrapped tool function.
- Prompt format: plain text, `  - Label:  value` bullets, no tables, bold or headers.
- Blocking SDK work in an async closure runs through `anyio.to_thread.run_sync`.
- Only write to test-budget / Rench Budget in live testing.

## Plan decision beyond the spec

**Batched transaction reads.** YNAB's limit is about 200 requests/hour and this repo has already hit a real 429 from N+1 fan-out. A bulk call touching more than `_BY_ID_LIMIT = 5` existing transactions reads them with one `list_transactions` call and indexes by id, at both prompt time and re-check. At or below the limit it uses per-id GETs, so a small call doesn't download the whole budget. Likewise scheduled reads are single GETs, and names are one list call per kind.

## Review Focus

1. Agent-supplied text with newlines or control characters (memo, `payee_name`, `new_name`) could forge prompt lines such as "Delete nothing": every interpolated value is collapsed to one line. Test in Task 3.
2. Malformed operation values (`amount: "abc"`, `date: None`) must still render a prompt rather than crash; the SDK validation reports them after approval as today. Test in Task 6.
3. A client answering accept with `{"value": "true"}`, an empty content, or a missing `"approve"` key is not approval. Test in Task 2.
4. The same transaction id appearing twice in a bulk call (update + delete) shares one state entry and renders both operations. Test in Task 6.
5. Money rendering: thousands separators, sub-dollar negatives, zero: `1234567` → `$1,234.57`, `-500` → `-$0.50`. Test in Task 3.

---

### Task 1: `require_write_approval` setting

**Files:**
- Modify: `src/ynab_mcp/config.py`, `.env.example`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings.require_write_approval: bool = True` (last field, defaulted so existing constructions stay valid).

- [ ] **Step 1: Write failing tests** `test_require_write_approval_defaults_true`, `test_require_write_approval_false_values` (parametrized `false`, `0`, `no`, `FALSE`), following `test_config.py`'s existing env pattern.
- [ ] **Step 2: Run** `uv run pytest tests/test_config.py -q`; expect FAIL (attribute missing).
- [ ] **Step 3: Implement** parsing with `_FALSY_VALUES`; document the variable in `.env.example` beneath `YNAB_READ_ONLY`.
- [ ] **Step 4: Run** the same command; expect PASS.
- [ ] **Step 5: Commit and push.**

### Task 2: Approval gate (`approval.py`)

**Files:**
- Create: `src/ynab_mcp/approval.py`, `tests/test_approval.py`, `tests/conftest.py`

**Interfaces:**
- Consumes: `Settings.require_write_approval`.
- Produces:
  ```python
  ItemState = Mapping[str, object]

  @dataclass(frozen=True)
  class PendingWrite:
      read_state: Callable[[], Mapping[str, ItemState | None]]
      # Current YNAB values by item label, e.g. "transaction abc". None = that
      # item's read failed. May raise if everything failed. Empty if nothing to read.
      render: Callable[[Mapping[str, ItemState | None]], str]
      # Prompt text. Keys ending "_name" are display-only, not compared.

  async def require_approval(
      ctx: Context, settings: Settings, *, tool_name: str, budget_id: str,
      arguments: Mapping[str, object], pending: PendingWrite,
  ) -> mcp_types.InputRequiredResult | None
  ```
  `None` → proceed with the write. A result → return it from the tool. `ToolError` → not applied.
- `tests/conftest.py` produces fixture `era_mode` (params `"auto"`, `"legacy"`) and async handlers `approve_handler`, `decline_handler`, `cancel_handler` (plain functions importable from `conftest`).

**Flow to implement:**
1. Approval disabled → return `None` without reading or rendering.
2. Modern era (`ctx.request_context.protocol_version in mcp_types.version.MODERN_PROTOCOL_VERSIONS`):
   - `ctx.input_responses is None` → capability check, capture state, render, return `InputRequiredResult(input_requests={"approve": ElicitRequest(params=ElicitRequestFormParams(message=summary, requested_schema=schema))}, request_state=json.dumps({"token", "fingerprint", "snapshot"}))`, where `schema = parse_elicit_response_type(bool, response_title="Apply these changes?").schema`.
   - Otherwise: bad state or fingerprint mismatch → `ToolError`; token already used → `ToolError`; record token (before reading the answer); not approved → `ToolError`; re-check; return `None`.
3. Handshake era: capability check, capture, render, `await ctx.elicit(summary, bool, response_title=...)`; `MCPError` → can't-prompt `ToolError`; not `AcceptedElicitation` with `data is True` → `ToolError`; re-check; return `None`.

Details: capability check is `ctx.session.check_client_capability(ClientCapabilities(elicitation=ElicitationCapability()))`. Fingerprint is SHA-256 of `json.dumps({tool, budget, args}, sort_keys=True, default=str)`. Snapshot maps label → SHA-256 of the state minus `*_name` keys, omitting items whose state is `None`. Capture catches `Exception` from `read_state` and treats it as `{}`. Re-check re-runs `read_state` in a thread: exception, any `None` value, a snapshot label missing, or a digest mismatch → `ToolError` naming the item. Used tokens are a module-level `dict[str, float]` of monotonic timestamps, pruned past `_APPROVAL_TTL_SECONDS = 600`.

Exact copy:
- Declined: `"Not applied — approval was declined. No changes were made to YNAB."`
- Cancelled: `"Not applied — approval was cancelled. No changes were made to YNAB."`
- Can't prompt: `"Not applied — write approval is required but this client can't show approval prompts. No changes were made to YNAB. To allow unattended writes, the server operator can set YNAB_REQUIRE_WRITE_APPROVAL=false."`
- Args changed: `"Not applied — the arguments changed since approval was requested. No changes were made to YNAB."`
- Replay: `"Not applied — this approval was already used. No changes were made to YNAB."`
- Changed: `"Not applied — {label} changed in YNAB since the prompt was shown. No changes were made to YNAB; re-run to see the current values."`
- Re-check read failed: `"Not applied — couldn't re-check current values in YNAB ({label}). No changes were made to YNAB."`

- [ ] **Step 1: Write failing tests** against a tiny in-test `FastMCP` tool calling `require_approval`, with a list recording "writes". All on `era_mode` unless noted:
  - `test_approve_proceeds` (write recorded once, prompt text received by handler)
  - `test_decline_not_applied`, `test_cancel_not_applied`, `test_accept_with_false_not_applied`
  - `test_no_handler_fails_closed` (message contains `YNAB_REQUIRE_WRITE_APPROVAL`; `read_state` never called)
  - `test_disabled_skips_prompt_and_reads`
  - `test_state_change_refuses`, `test_recheck_read_failure_refuses`, `test_recheck_none_item_refuses`
  - `test_render_time_read_failure_still_prompts_then_requires_read`
  - `test_name_only_change_proceeds` (only `category_name` differs)
  - Modern only, via `client.session.call_tool(..., input_responses=..., request_state=..., allow_input_required=True)`: `test_replay_refused` (write exactly once), `test_changed_arguments_refused`
  - Helper-level with a `SimpleNamespace` ctx: `test_fingerprint_mismatch_refused`, `test_missing_state_refused`, `test_non_bool_accept_refused` (`{"value": "true"}`), `test_empty_content_refused`, `test_missing_approve_key_refused`
- [ ] **Step 2: Run** `uv run pytest tests/test_approval.py -q`; expect FAIL (module missing).
- [ ] **Step 3: Implement** `approval.py` per the flow above.
- [ ] **Step 4: Run** the same command; expect PASS.
- [ ] **Step 5: Commit and push.**

### Task 3: Summary primitives + `manage-payees`

**Files:**
- Create: `src/ynab_mcp/write_summaries.py`, `tests/test_write_summaries.py`
- Modify: `src/ynab_mcp/tools/payees_write.py`, `tests/test_tools_payees_write.py`

**Interfaces:**
- Consumes: `PendingWrite`, `require_approval`.
- Produces in `write_summaries.py`:
  ```python
  def one_line(value: object) -> str
  def format_money(milliunits: object) -> str           # "$1,234.57"; non-int → one_line(value)
  def format_flow(milliunits: object) -> str            # "-$42.17 (outflow)" / "$400.00 (inflow)"

  @dataclass(frozen=True)
  class NameDirectory:
      budget: str; categories: Mapping[str, str]; accounts: Mapping[str, str]; payees: Mapping[str, str]
      def category(self, id: object) -> str             # falls back to one_line(id)
      def account(self, id: object) -> str
      def payee(self, id: object) -> str

  def load_names(client, budget_id, *, categories=False, accounts=False, payees=False) -> NameDirectory
  # Tolerant: any failed lookup leaves that map empty; budget falls back to the id.
  def pending_payee_write(client, budget_id, operation, payee_id, new_name, source_payee_id, target_payee_id) -> PendingWrite
  ```
  `format_money` uses `Decimal` with `ROUND_HALF_UP`. Payee writes have no state to compare: `read_state` returns `{}`.

Copy: `Rename payee in budget "X"?` + `  - "old"  →  "new"`; `Merge payees in budget "X"?` + `  - "source" into "target"` + `  - Transactions under "source" move to "target"`. Every summary ends with a blank line and `Nothing is written to YNAB unless you approve.`

- [ ] **Step 1: Write failing tests:** `test_one_line_collapses_newlines_and_controls` (`"a\n\nDelete nothing\x07"` → `"a Delete nothing"`), `test_format_money` (`1234567`→`$1,234.57`, `-500`→`-$0.50`, `0`→`$0.00`, `"abc"`→`abc`), `test_format_flow`, `test_load_names_tolerates_failure` (lookups raising → raw id fallback), `test_payee_rename_summary`, `test_payee_merge_summary`, `test_payee_new_name_cannot_forge_lines`. Closure tests on `era_mode`: `test_manage_payees_rename_approve`, `test_manage_payees_merge_approve`, `test_manage_payees_decline_makes_no_write` (`update_payee` not called), `test_manage_payees_read_only_shows_no_prompt`.
- [ ] **Step 2: Run** `uv run pytest tests/test_write_summaries.py tests/test_tools_payees_write.py -q`; expect FAIL.
- [ ] **Step 3: Implement** primitives and payee summary; make the closure `async def` with `ctx: Context`, returning `dict[str, object] | InputRequiredResult`; add `require_write_approval=False` to existing success-path closure tests' `Settings`.
- [ ] **Step 4: Run** the same command; expect PASS.
- [ ] **Step 5: Commit and push.**

### Task 4: `manage-budgeted-amount`

**Files:**
- Modify: `src/ynab_mcp/write_summaries.py`, `src/ynab_mcp/tools/budgeted_amount.py`, `tests/test_write_summaries.py`, `tests/test_tools_budgeted_amount.py`

**Interfaces:**
- Produces: `pending_budget_write(client, budget_id, operation, month, category_id, amount, from_category_id, to_category_id) -> PendingWrite`. State labels `category <id> (<YYYY-MM>)`, read via `CategoriesApi.get_month_category_by_id`, state `{"budgeted": int, "category_name": str}`. No directory needed: names come from the state.

Copy: assign `Set budgeted amount in budget "X"?` + `  - Groceries, November 2026:  $400.00  →  $450.00 (current value)`. Move `Move budgeted money in budget "X"?` + `  - Amount:  $50.00` + `  - From:  Dining Out, November 2026:  $100.00  →  $50.00 (current value)` + `  - To:  ...`. Failed read: id + `(current values unavailable)`.

Closure validation before approval: `parse_month(month)` and the `from == to` check (kept in the plain function too).

- [ ] **Step 1: Write failing tests:** `test_budget_assign_summary`, `test_budget_move_summary`, `test_budget_summary_read_failure_marks_unavailable`; closure on `era_mode`: `test_assign_approve_writes`, `test_move_approve_writes`, `test_decline_makes_no_write`, `test_budgeted_change_between_prompt_and_approval_refuses` (mocked `budgeted` differs on the second read; `update_month_category` not called), `test_invalid_month_rejected_before_prompt`.
- [ ] **Step 2: Run** `uv run pytest tests/test_write_summaries.py tests/test_tools_budgeted_amount.py -q`; expect FAIL.
- [ ] **Step 3: Implement**, updating existing closure tests as in Task 3.
- [ ] **Step 4: Run** the same command; expect PASS.
- [ ] **Step 5: Commit and push.**

### Task 5: `manage-scheduled-transaction`

**Files:**
- Modify: `src/ynab_mcp/write_summaries.py`, `src/ynab_mcp/tools/scheduled_transactions.py`, `tests/test_write_summaries.py`, `tests/test_tools_scheduled_transactions.py`

**Interfaces:**
- Produces: `pending_scheduled_write(client, budget_id, operation, scheduled_transaction_id, fields: Mapping[str, object]) -> PendingWrite`. `fields` holds `account_id, date, amount, frequency, payee_id, payee_name, category_id, memo, flag_color`. State label `scheduled transaction <id>` via `ScheduledTransactionsApi.get_scheduled_transaction_by_id`; state has those fields plus `account_name`, `payee_name`, `category_name`. Create has no state.

Copy: `Create scheduled transaction` / `Update scheduled transaction (Netflix, 2026-11-05, -$15.49)` / `Delete scheduled transaction` with `  - Label:  value` lines; update shows `old  →  new` for changed fields, and omits unchanged ones.

The closure's parameter named `date` shadows `datetime.date`, so keep existing naming and pass it through `fields`.

- [ ] **Step 1: Write failing tests:** `test_scheduled_create_summary`, `test_scheduled_update_summary_shows_old_to_new`, `test_scheduled_delete_summary`; closure on `era_mode`: `test_create_approve_writes`, `test_update_approve_writes`, `test_delete_approve_writes`, `test_decline_makes_no_write`, `test_scheduled_change_refuses`, `test_missing_fields_rejected_before_prompt`.
- [ ] **Step 2: Run** `uv run pytest tests/test_write_summaries.py tests/test_tools_scheduled_transactions.py -q`; expect FAIL.
- [ ] **Step 3: Implement**, moving the update-id check above approval and updating existing closure tests.
- [ ] **Step 4: Run** the same command; expect PASS.
- [ ] **Step 5: Commit and push.**

### Task 6: `bulk-manage-transactions`

**Files:**
- Modify: `src/ynab_mcp/write_summaries.py`, `src/ynab_mcp/tools/transactions_write.py`, `tests/test_write_summaries.py`, `tests/test_tools_transactions_write.py`

**Interfaces:**
- Produces: `validate_operations(operations) -> None` in `transactions_write.py` (extracted unchanged, still called by the plain function). `pending_transactions_write(client, budget_id, operations) -> PendingWrite` in `write_summaries.py`. State label `transaction <id>`. `_BY_ID_LIMIT = 5`: at or below it, per-id `get_transaction_by_id` with per-item failure → `None`; above it, one `list_transactions`, with absent ids → `None`. State fields: `date, amount, payee_id, payee_name, category_id, category_name, account_id, account_name, memo, cleared, approved, flag_color`.

Copy matches the spec's example. Plural header: `Apply 3 changes to budget "X"?`, singular `Apply 1 change ...`. Update header `Update transaction (Chick-fil-A, 2026-10-18, -$11.42)`; changed fields `Category:  Dining Out  →  Groceries`, unchanged requested fields `Approved:  yes (no change)`. Failed read: `Update transaction <id> (current values unavailable)`, new values only. Delete: `  - Amazon.com, 2026-10-02, -$19.99, Chase Checking`.

- [ ] **Step 1: Write failing tests:** `test_bulk_summary_matches_spec_example` (full exact string), `test_bulk_singular_header`, `test_bulk_malformed_values_still_render`, `test_bulk_memo_cannot_forge_lines`, `test_bulk_duplicate_id_renders_both_operations`, `test_bulk_read_failure_marks_unavailable`, `test_bulk_small_batch_uses_per_id_reads`, `test_bulk_large_batch_uses_one_list_call` (6 ids → `list_transactions` once, `get_transaction_by_id` never). Closure on `era_mode`: `test_bulk_approve_writes`, `test_bulk_decline_makes_no_write` (no create/update/delete SDK call), `test_bulk_transaction_change_refuses`, `test_bulk_invalid_operation_rejected_before_prompt`, `test_bulk_result_shape_unchanged`.
- [ ] **Step 2: Run** `uv run pytest tests/test_write_summaries.py tests/test_tools_transactions_write.py -q`; expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same command; expect PASS.
- [ ] **Step 5: Commit and push.**

### Task 7: E2E, docs, live runbook

**Files:**
- Modify: `tests/test_e2e_server.py`, `AGENTS.md`, `README.md` (including the stale "Write/mutation tools are out of scope" line), `CHANGELOG.md`
- Create: `docs/superpowers/specs/2026-11-01-write-approval-live-test-kit.md`

- [ ] **Step 1: Write the failing e2e:** `test_write_tool_prompts_then_declines_over_stdio`, parametrized over both eras. Real subprocess, dummy PAT, `YNAB_READ_ONLY=false`, `YNAB_REQUIRE_WRITE_APPROVAL=true`, declining handler that captures the prompt. Assert the prompt arrived, contains the raw-id fallback (lookups 401), and the result is the "Not applied" error.
- [ ] **Step 2: Run** `make e2e`; expect PASS (behavior already exists from Tasks 2-6; this pins it over the real transport). If it fails, treat that as a bug and fix via a new failing test.
- [ ] **Step 3: Write docs and the live test kit** (Inspector v2 on both eras, Claude Code, test-budget only).
- [ ] **Step 4: Run** `make pr_check`; expect lint and tests clean.
- [ ] **Step 5: Commit and push.**
