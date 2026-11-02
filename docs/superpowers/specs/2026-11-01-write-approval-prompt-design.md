# Approval prompt before YNAB write tools — design

Issue: #45 (parent epic #10, child 13). Builds on #43 (FastMCP 4 / MCP SDK v2,
merged). Coordinates with #33 (per-budget `require_writable`), which reworks the
same four write closures.

## Intent

With `YNAB_READ_ONLY=false`, the four write tools — `bulk-manage-transactions`,
`manage-budgeted-amount`, `manage-payees`, `manage-scheduled-transaction` —
execute the moment an agent calls them. A bad categorization pass or a duplicated
create lands in a real household budget (Rench Budget) before any human sees it.
This feature puts a human checkpoint in front of every write: the server shows a
**readable** summary of exactly what is about to change and only proceeds on an
explicit yes.

Success: a human reviewing the prompt can tell, without opening YNAB, whether the
write is right — which transaction, which category/payee/account by *name*, how
much money in dollars.

## Goals

- Every call to any of the four write tools asks for approval before any YNAB
  **write** call.
- The prompt is human-readable on every client: plain text that also reads well
  when a client renders it as markdown.
- Decline / cancel / dismiss → zero YNAB write calls, clear "not applied" result.
- Approve → the write executes exactly as it does today (same plain functions,
  same results, same retry rules).
- Works on both MCP protocol eras the server serves.
- A server-level opt-out for unattended runs (e.g. the scheduled monthly report
  skill, #28).

## Non-goals

- Per-budget write gating (#32/#33).
- Partial approval (approve 2 of 3 operations in a bulk call). It is all-or-nothing
  per tool call; the agent can re-call with fewer operations.
- Editing the pending write inside the prompt.
- Changing what the write tools do once approved.

## Anti-goals (failure even if it "works")

- **A write lands without a human yes while approval is enabled** — including when
  the client can't show a prompt, when the approval round is replayed/tampered, or
  when the arguments change between ask and approve.
- **An agent can turn approval off by itself.** No per-call parameter bypasses
  approval; only the server operator's environment can.
- **An unreadable prompt** (raw ids, milliunits, JSON dumps) that trains the human
  to click through.

## Decisions (made with the user)

1. **Gate order inside every write closure:** `require_writable(settings)` →
   `resolve_budget_id(...)` → required-field validation (existing `ToolError`s) →
   **approval** → existing write call. Validation stays before approval so the user
   is never asked to approve a call that would be rejected anyway. #33 later swaps
   the first two lines; approval stays after both. *(My call:)* for
   `bulk-manage-transactions`, whose per-operation field checks currently live
   inside the plain `bulk_manage_transactions` function, extract them into a
   validator that both the closure (before approval) and the plain function call,
   so the plain function's behavior is unchanged.
2. **Names, not ids, in the prompt.** Resolving names requires YNAB **read** calls
   before approval. The issue's acceptance criterion is reworded from "zero YNAB API
   calls" to **"zero YNAB write calls"** on decline. Reads are GETs, wrapped in
   `call_with_retry` per the repo convention, and cannot change anything.
3. **Lookup failure never blocks:** if a name lookup fails (any exception, incl.
   `ApiException`), the prompt falls back to showing the raw id for that item and
   still asks. It does not raise.
4. **Prompt format:** plain-text, markdown-tolerant — line breaks, two-space-indented
   `- Label:  value` bullets, no tables/bold/headers. Example (bulk transactions):

   ```
   Apply 3 changes to budget "Rench Budget"?

   Create transaction
     - Date:      2026-10-20
     - Payee:     Boyert's
     - Amount:    -$42.17 (outflow)
     - Category:  Home & Garden
     - Account:   Chase Checking

   Update transaction (Chick-fil-A, 2026-10-18, -$11.42)
     - Category:  Dining Out  →  Groceries

   Delete transaction
     - Amazon.com, 2026-10-02, -$19.99, Chase Checking

   Nothing is written to YNAB unless you approve.
   ```

5. **Response shape:** a single boolean confirmation (`response_type=bool`, titled
   e.g. "Apply these changes?"). Approved = `accept` **and** value `True`.
   `accept` with `False`, `decline`, and `cancel` are all "not applied".
6. **"Not applied" result:** raise `ToolError("Not applied — approval was declined.
   No changes were made to YNAB.")` (wording may vary per outcome: declined vs.
   cancelled). A `ToolError` (is_error result) is deliberate: the agent must not
   mistake a declined write for a success.
7. **Fail closed when the client can't prompt:** if approval is enabled and the
   client cannot elicit (no elicitation capability, or the elicit attempt errors),
   raise `ToolError` explaining that write approval is required, the client can't
   show approval prompts, and the operator can set
   `YNAB_REQUIRE_WRITE_APPROVAL=false` for unattended use. No write happens.
8. **Opt-out:** `YNAB_REQUIRE_WRITE_APPROVAL` env var, default `true`, parsed in
   `Settings.from_env()` with the same falsy set as `YNAB_READ_ONLY`
   (`false`/`0`/`no`) into a new `Settings.require_write_approval: bool`. When
   `false`, the approval step is skipped entirely (no name lookups either) and
   writes behave exactly as today. Document it in `.env.example` and README.
9. **Claude Code support is an open fact to verify live**, not to design around.
   If Claude Code can't show prompts, the fail-closed default blocks writes from
   Claude Code skills until the opt-out is set — that's acceptable and must be
   called out in the README/live test results.

## Mechanism — two protocol eras

FastMCP 4.1.4 enforces a hard split (verified in source):

- **`2026-07-28` (modern):** `ctx.elicit()` raises `ToolError` ("elicitation via
  server-initiated requests is unavailable"). The tool must use the **guard
  pattern**: return `mcp.types.InputRequiredResult(input_requests={"approve":
  ElicitRequest(params=ElicitRequestFormParams(message=..., requested_schema=...))},
  request_state=...)`. The client answers and **re-calls the tool** with
  `ctx.input_responses` / `ctx.request_state` populated.
- **Handshake era (≤ `2025-11-25`):** returning `InputRequiredResult` is rejected by
  FastMCP with an `MCPError`; the tool must `await ctx.elicit(message, bool)`.

So the shared helper branches on the negotiated era (FastMCP's
`Context._is_modern_protocol()` is private; the builder should use
`ctx.request_context.protocol_version in MODERN_PROTOCOL_VERSIONS` or an equivalent
public check).

### Modern-era round binding (anti-tamper + single-use)

What the SDK already gives us (verified in `mcp/server/request_state.py`): the
sealed `request_state` is authenticated-encrypted under a per-process key, bound to
the tool name + a digest of the call's arguments, and expires after 600 s. It is
**not** single-use — a client could resend an approved round 2 repeatedly within
the window. Decisions on top of that:

- Round 1 (`ctx.input_responses is None`): build the summary (with lookups); return
  `InputRequiredResult` with the prompt and `request_state` = JSON carrying
  (a) a fresh random approval token, (b) an argument fingerprint (SHA-256 of
  canonical JSON of tool name, resolved budget id, all write arguments —
  defense-in-depth should the SDK binding ever be configured away), and (c) the
  **state snapshot** (below).
- Round 2 (`input_responses` present):
  1. Fingerprint mismatch or missing/unparseable state → `ToolError`
     ("arguments changed since approval was requested — not applied").
  2. **Single-use (user decision):** if the token is already in the server's
     in-process used-token record → `ToolError` ("this approval was already used —
     not applied"). Otherwise record the token as used **before** acting on the
     answer (whether accept or decline), so a replay can never execute. The record
     is in memory, pruned of entries older than the 600 s TTL; a restart wipes it,
     which is safe because a restart also invalidates every sealed state.
     Consequence (accepted): a client that legitimately retries an approved round 2
     after a network glitch is refused and must start over with a new prompt.
  3. Read the `"approve"` `ElicitResult`; not approved → "not applied".
  4. Approved → the write-time re-check (below), then the write.
  No name lookups on round 2 beyond what the re-check needs.
- A server restart between rounds invalidates the sealed state → FastMCP rejects
  it; that's a correct "not applied".

### Write-time re-check of shown values (both eras — user decision)

Where the prompt shows **current** values from YNAB (anything rendered as
`old → new`, or the identifying details of a transaction being deleted), the user
is approving against that snapshot. Between prompt and approval YNAB may change
(the human can take minutes; a `move` is relative, so its "after" would silently
differ). So:

- When rendering, the helper also captures a **state snapshot**: a canonical,
  comparable record of the current values the prompt depends on —
  budgeted amount (and month) of every category in an assign/move; the existing
  transaction's fields for each bulk update/delete; the existing scheduled
  transaction's fields for scheduled update/delete. Names are **not** part of the
  snapshot (a category rename doesn't change what the write does). Creates and
  payee rename/merge have no snapshot beyond what the write itself specifies (for
  merge, the source and target payees must still exist — the existing write path
  already errors if not).
- After approval and immediately before the write, re-read the same values
  (`call_with_retry`-wrapped reads, as for rendering) and compare to the snapshot.
  Any difference → `ToolError` ("<item> changed in YNAB since you approved —
  not applied; re-run to see the current values"), zero writes. A read failure
  during the re-check also refuses (fail closed) — unlike rendering, where a lookup
  failure only degrades to raw ids.
- If a snapshot read failed at render time (raw-id fallback), that item has no
  snapshot; the re-check then requires the read to succeed and the write proceeds
  only if it does — the user approved without seeing current values, which the
  prompt must say for that item (e.g. "current values unavailable").
- Modern era: the snapshot travels in the sealed `request_state`. Handshake era:
  it stays in the coroutine's local variable across `await ctx.elicit(...)`.
- Residual race (accepted, documented): a change landing between the re-check and
  the write isn't caught. The window is one round-trip, not the human's think time.

### Shared module: `src/ynab_mcp/approval.py`

One public coroutine, roughly:

```python
async def require_approval(
    ctx: Context, settings: Settings, *, tool_name: str, budget_id: str,
    arguments: dict[str, object], render: Callable[[], str],
) -> InputRequiredResult | None
```

- Returns `None` → caller proceeds with the write.
- Returns an `InputRequiredResult` → caller returns it as the tool result
  (modern round 1).
- Raises `ToolError` → not applied (declined/cancelled/tampered/can't-prompt).
- `render` is called lazily so disabled approval / round 2 never does lookups.

Each write closure becomes `async def`, takes `ctx: Context`, and its return
annotation becomes `<existing> | InputRequiredResult` (FastMCP strips that arm from
the output schema). Blocking SDK calls (both the summary lookups and the existing
plain write functions) must not block the event loop — run them via
`anyio.to_thread.run_sync` (or FastMCP's equivalent).

### Summary renderers

Per-tool rendering functions live next to each tool (or in `approval.py` — builder's
call), are pure given a small "name directory" (ids → names) so they're
fixture-testable without the SDK, and format money from milliunits as
`-$42.17 (outflow)` / `$400.00 (inflow)`.

| Tool / operation | Lines shown | Lookups |
|---|---|---|
| bulk create | date, payee (name or `payee_name`), amount, category, account, memo/flag/cleared/approved if set | categories, accounts, payees (one list call each, per tool call) |
| bulk update | header: existing txn's payee, date, amount; then only the fields being set, as `old → new` where old is known | + one `get_transaction_by_id` per update |
| bulk delete | existing txn's payee, date, amount, account | one `get_transaction_by_id` per delete |
| budgeted-amount assign | category, month, `current → new` budgeted | month's categories (one `get_plan_month`) |
| budgeted-amount move | from/to category, month, amount moved, each category's `before → after` | same |
| payees rename | `"old" → "new"` | payees |
| payees merge | `Merge "source" into "target"` + what merge does (reassigns source's transactions, per existing `merge_payees`) | payees |
| scheduled create/update/delete | account, date, frequency, amount, payee, category, memo; update shows `old → new` | accounts, categories, payees, + `get_scheduled_transaction_by_id` for update/delete |

Budget name in the header comes from one budget lookup (or the plan settings); falls
back to the id. Large bulk calls: list every operation (no truncation) — the human
should see everything they approve. Builder may cap per-item detail lines if a
single call exceeds ~50 operations, but must keep a one-line entry per operation.

Any SDK method named here is a pointer, not a contract — use whatever existing tool
module function already wraps that read (`categories.py`, `accounts.py`,
`payees.py`, `transactions.py`, `months.py`) per the repo's reuse convention.

## Testing

`fastmcp.Client`-based tests, **parametrized over both eras** (`mode="auto"` →
`2026-07-28`, `mode="legacy"` → handshake era, matching `tests/test_e2e_server.py`),
with an `elicitation_handler` that approves / declines / cancels. The FastMCP
client drives the modern guard round-trip through the same handler.

Per write tool, at minimum:
- approve → write plain function called with the same args as today;
- decline and cancel → `ToolError` "not applied", **zero write calls** (assert on
  mocked SDK write methods);
- `YNAB_READ_ONLY=true` → `require_writable` error, no prompt shown, no lookups;
- approval disabled → no prompt, write executes.

Shared/helper tests:
- client with no elicitation handler → fail-closed `ToolError`, zero writes (both eras);
- modern-era tamper: round 2 with changed arguments or missing state → `ToolError`;
- modern-era replay: resending an approved round 2 → second attempt `ToolError`,
  write called exactly once;
- write-time re-check, both eras: YNAB value changes between prompt and approval
  (e.g. a category's budgeted amount, an updated transaction's amount) →
  `ToolError`, zero writes; re-check read failure → `ToolError`, zero writes;
  unchanged → write proceeds;
- lookup failure → prompt still shown with raw id fallback;
- renderer unit tests per tool (money formatting, `old → new`, name fallback);
- `Settings.from_env()` parses `YNAB_REQUIRE_WRITE_APPROVAL` (default true, falsy set).

Existing write-tool closure tests must be updated: they now need either approval
disabled in their `Settings` or an approving handler. The repo's pytest config fails
on any `FastMCPDeprecationWarning`; the new code must not trip it.

E2E: extend the stdio e2e (or add one) so the real subprocess shows a write
tool returning the approval request on both eras, with a declining handler and a
dummy PAT. With `YNAB_READ_ONLY=false` and a dummy PAT, name lookups fail (401) —
which also exercises the raw-id fallback — and decline proves nothing was written.

## Live verification (issue acceptance)

Against the **test-budget** (allowed writes: test-budget and Rench Budget only):
MCP Inspector v2 on both eras, and Claude Code. Record per client whether the prompt
renders, how it looks (screenshot), and that approve/decline behave. The Claude Code
outcome decides the README guidance on `YNAB_REQUIRE_WRITE_APPROVAL`.

## Left to the builder

- Exact helper signature and file split (renderers inline vs. one module).
- Exact wording of "not applied" / can't-prompt messages (keep the meaning above).
- How to detect "client can't elicit" on each era (capability check vs. catching
  the elicit error) — either is fine as long as it fails closed.
- Whether to reuse existing tool-module read functions or call the SDK directly
  for lookups (prefer reuse; wrap any direct call in `call_with_retry`).

## Docs to update when shipping

`AGENTS.md` (approval step in the write-closure description, new env var),
`README.md`, `.env.example`, `CHANGELOG.md`.
