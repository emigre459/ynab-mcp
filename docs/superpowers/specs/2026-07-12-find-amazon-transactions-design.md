# find_amazon_transactions — Amazon Order Matching Tool — Design

- **Issue:** [#15](https://github.com/emigre459/ynab-mcp/issues/15) — find_amazon_transactions — Amazon order matching tool
- **Parent epic:** [#10](https://github.com/emigre459/ynab-mcp/issues/10) — AI-driven budget coaching & categorization for parents' YNAB budget
- **Date:** 2026-07-12

## Why

Amazon is the single biggest source of hard-to-categorize transactions in the founding
use case. Automating the join between a YNAB transaction and the real Amazon order it
came from removes the most tedious part of manual categorization. This card is child 5
of epic #10, parallel with children 2–4, and naturally pairs with the write-tools card
(#12) later — but this card **only proposes matches**; applying a categorization from a
match is explicitly out of scope here.

## Key finding: Amazon exposes per-charge transaction records, not just order totals

The `amazon-orders` PyPI library (confirmed reusable per epic #10's research — no
reusable merge-key/join logic exists upstream, so this card designs the matching
algorithm from scratch) exposes two distinct APIs:

- `AmazonOrders.get_order_history()` / `get_order()` → `Order` objects, keyed by
  `order_number`, carrying `grand_total` (the order's *total*, which can span multiple
  shipments/charges) and `items: list[Item]`.
- `AmazonTransactions.get_transactions(days=...)` → `Transaction` objects: each one is a
  **single charge or refund event** — `completed_date`, `grand_total` (the charge
  amount), `payment_method`, `payment_method_last_4`, `is_refund`, `order_number`,
  `seller`.

A `Transaction` record maps 1:1 to what actually posts to a bank/credit-card statement
— including each individual leg of a split-shipment order, which Amazon charges
separately as the shipments go out. This means the join target for YNAB transactions is
`Transaction`, not `Order.grand_total`: **no amount-tolerance/fuzziness is needed**, only
a small date window to absorb bank posting lag. `order_number` is the join key back to
`Order`/`Item` when we need product-level detail for the reasoning text, and it's what
groups multiple `Transaction` legs as one split-shipment order.

## Module layout

```
src/ynab_mcp/
  config.py               # + AmazonSettings.from_env() (new; fail-soft — see below)
  amazon_client.py        # new: AmazonSession/AmazonOrders/AmazonTransactions factory
  amazon_matching.py      # new: pure match_transactions() — no I/O, fixture-testable
  tools/
    find_amazon_transactions.py   # new: tool function + register()
scripts/
  amazon_login.py         # new: one-time interactive Amazon login
```

This mirrors the existing `config.py` / `client.py` / `errors.py` / `tools/*.py` split
from the server-foundation card (#11), with one deliberate difference: `amazon_matching.py`
is a new kind of module this codebase hasn't needed yet — a pure algorithm with no
client dependency at all, isolated specifically so the acceptance criteria's fixture-based
unit tests (exact/near-date/split-shipment/ambiguous/no-match) need zero mocking of either
API.

## Config (`config.py` addition) — fail-soft, unlike `YNAB_PAT`

```python
@dataclass(frozen=True)
class AmazonSettings:
    amazon_username: str
    amazon_password: str
    amazon_otp_secret_key: str | None

    @classmethod
    def from_env(cls) -> "AmazonSettings | None":
        ...
```

- Reads `AMAZON_USERNAME`, `AMAZON_PASSWORD`, `AMAZON_OTP_SECRET_KEY` (optional, for
  OTP-based 2FA) — the same env-var names the `amazon-orders` library itself reads by
  convention, kept identical so `scripts/amazon_login.py` and the library's own defaults
  line up.
- **Returns `None`** (not a raised error) when `AMAZON_USERNAME`/`AMAZON_PASSWORD` are
  unset. Unlike `YNAB_PAT`, Amazon configuration is optional server-wide functionality —
  a user who hasn't set up Amazon yet must still get a fully working YNAB-only server.
  This is the one deliberate asymmetry with `Settings.from_env()`'s fail-hard behavior,
  and it's why `AmazonSettings` is a separate dataclass rather than new fields bolted
  onto `Settings`.
- `.env.example` gains the three new variables, documented as optional, alongside a
  pointer to `scripts/amazon_login.py`.

## Amazon session/client (`amazon_client.py`)

```python
def build_amazon_transactions(settings: AmazonSettings) -> ynab_mcp_amazon.AmazonTransactions: ...
def build_amazon_orders(settings: AmazonSettings) -> ynab_mcp_amazon.AmazonOrders: ...
```

Mirrors `client.py`'s `build_api_client`: constructs an `AmazonSession` from
`AmazonSettings`, then the `AmazonOrders` and `AmazonTransactions` wrappers, once at
server startup (only when `AmazonSettings.from_env()` returned non-`None`), reused for
the process lifetime.

**Session persistence and first login.** `amazon-orders`' `AmazonSession` may require
solving a CAPTCHA or approving a device/OTP challenge on first login — something an MCP
stdio tool call cannot do mid-request (no interactive terminal reachable from inside a
tool invocation). So first login is **never** attempted inside a tool call:

**Correction from live testing (2026-07-13):** real Amazon logins commonly present a
JavaScript-based bot-detection/"ACIC" challenge. The `amazon-orders` library's default
auth-form chain only *blocks* on this (raising `AmazonOrdersAuthError` with a
remediation hint) unless the library's Playwright-backed solver forms are explicitly
registered. `pyproject.toml` now declares `amazon-orders[browser]` (not the bare
package), and `build_amazon_session()` passes an `AmazonOrdersConfig(data={
"auth_forms_classes": [...]})` registering `PlaywrightAcicForm` and
`PlaywrightJSAuthForm`, so `scripts/amazon_login.py` can drive a real (headless)
browser through the challenge automatically. Requires a one-time
`uv run playwright install chromium` per machine.

- `scripts/amazon_login.py` is a standalone script (`uv run python scripts/amazon_login.py`)
  that builds an `AmazonSession` from `AmazonSettings.from_env()` and calls `.login()`
  interactively, letting the library persist its session to disk as it normally does.
  Run once (or again after the session expires).
- `server.py` registers `find-amazon-transactions` only when `AmazonSettings.from_env()`
  succeeds — an unconfigured server never even attempts to build the Amazon client.

**Correction from live testing (2026-07-14):** the original design said
`amazon_client.py`'s factory "only reuses an existing persisted session — it never calls
`.login()`," and that a missing/expired session would only surface on the first real API
call. This was wrong: `amazon-orders`' `AmazonOrders`/`AmazonTransactions` methods gate on
`AmazonSession.is_authenticated`, which is set `True` **only** inside `.login()` — loading
persisted cookies at construction time is not sufficient by itself, so every tool call
failed with `"Call AmazonSession.login() to authenticate first."` regardless of a valid
persisted session. `login()`'s own docstring confirms calling it is safe outside a tool
call: it fast-paths to a single request when valid cookies are already persisted (no
interactive challenge), and only drives the full auth-form chain when the session is
genuinely missing/expired. The fix: `server.py` calls `amazon_session.login()` exactly
**once**, at startup, right after `build_amazon_session()` — never inside a tool call, but
no longer skipped entirely either. On failure it's caught and the tool is skipped for that
run (fail-soft, printed to stderr) rather than registered in a permanently-broken state.

## Matching algorithm (`amazon_matching.py`)

Pure function, no I/O:

```python
def match_transactions(
    ynab_transactions: list[YnabCandidate],
    amazon_transactions: list[AmazonCandidate],
    date_window_days: int = 3,
) -> MatchResult:
    ...
```

Where `YnabCandidate`/`AmazonCandidate` are small plain dataclasses carrying only the
fields the algorithm needs (id, date, amount, order_number for Amazon-side) — decoupled
from `ynab.TransactionDetail` and the `amazon-orders` SDK's `Transaction` class so the
matcher has zero import dependency on either client library, and fixtures in tests stay
trivial to construct.

**Pipeline:**

1. **Filter YNAB candidates.** Caller (the tool function) pre-filters YNAB transactions
   to Amazon-like payees: case-insensitive substring match on `"amazon"` / `"amzn"`.
2. **Filter Amazon candidates.** Caller pre-filters Amazon `Transaction` records to
   exclude `is_refund` and Whole-Foods charges. `Transaction` has no `is_whole_foods`
   flag (that lives on `Order`), so the proxy is a case-insensitive `"whole foods"`
   substring check against `Transaction.seller` — cheap, no extra API call, and Whole
   Foods consistently identifies itself as the seller on these charge records.
3. **Join.** For each YNAB candidate, find Amazon candidate(s) whose `amount` **exactly**
   equals the YNAB amount and whose `date` falls within `date_window_days` of the YNAB
   date (inclusive, either direction).
4. **Classify each YNAB candidate**, in two passes:

   **Pass 1 — per-candidate match count** decides the base bucket:
   - **0 Amazon candidates in range** → **`no-match`**.
   - **≥2 Amazon candidates tie** (same amount, all within the date window) for one
     YNAB candidate, or one Amazon candidate ties equally between two+ YNAB candidates
     → **`ambiguous`**. Per the issue's acceptance criteria, ambiguous cases are
     **surfaced, not auto-resolved** — the result lists every tied candidate so a human
     can pick.
   - **Exactly 1 Amazon candidate matches, uniquely** → provisionally `exact` (same
     calendar date) or `near-date` (date within the window but not the same day).

   **Pass 2 — split-shipment regrouping**, over every YNAB candidate that landed in the
   `exact`/`near-date` bucket: group their matched Amazon `Transaction`s by
   `order_number`. Any group with more than one member means that Amazon order was
   charged in multiple shipments, each already uniquely matched to its own YNAB
   transaction — relabel every member's classification to **`split-shipment`**
   (retaining whether each individual leg was same-day or near-date in its `reasoning`
   text) and populate `split_group` with the sibling YNAB transaction ids. Singleton
   groups keep their pass-1 `exact`/`near-date` label unchanged.
5. **Order-level enrichment.** The tool function (not the pure matcher) fetches
   `AmazonOrders.get_order(order_number)` for matched results to pull `Item` titles into
   the reasoning text — done as a **follow-up call only for matches that need it**, not
   for every Amazon `Transaction`, since `full_details`/per-order fetches are the slow
   path in this library.

## Tool interface (`tools/find_amazon_transactions.py`)

```python
@mcp.tool(name="find-amazon-transactions")
def find_amazon_transactions_tool(
    budget_id: str | None = None,
    since_date: date | None = None,
    until_date: date | None = None,
    date_window_days: int = 3,
) -> dict[str, object]:
    ...
```

Mirrors `list-transactions`' `budget_id`/`since_date`/`until_date` defaulting via
`resolve_budget_id`. Internally: calls `list_transactions()` (reused from
`tools/transactions.py`, not re-implemented) for the YNAB side, `AmazonTransactions
.get_transactions(days=...)` for the Amazon side (days derived from the requested date
window), pre-filters both per the matching algorithm's step 1–2, calls
`match_transactions()`, then enriches and shapes the result:

```json
{
  "matches": [
    {
      "ynab_transaction": { ... },
      "amazon_transaction": { ... },
      "order_number": "...",
      "classification": "exact" | "near-date" | "split-shipment",
      "reasoning": "Exact amount+date match against Amazon order #... (2 items: ...)",
      "split_group": ["<other ynab txn ids in this order>"]   // only for split-shipment
    }
  ],
  "ambiguous": [
    {
      "ynab_transaction": { ... },
      "candidates": [ { "amazon_transaction": { ... }, "order_number": "..." }, ... ],
      "reasoning": "N Amazon transactions tie for this amount within the date window."
    }
  ],
  "unmatched": [
    { "ynab_transaction": { ... }, "reasoning": "No Amazon transaction found in range." }
  ]
}
```

No categorization is written back to YNAB — this tool is read-only, matching the issue's
explicit out-of-scope note (applying matches is card #12's job).

## Error handling

- `AmazonSettings.from_env()` returning `None` → `find-amazon-transactions` is never
  registered on the server (see `server.py` change below); no runtime "not configured"
  error path is needed.
- Amazon session missing/expired **at server startup** → `amazon_session.login()`
  (called once in `server.py`, see the correction note above) raises; caught there,
  logged to stderr, and the tool is skipped for this run rather than registered.
- Amazon session missing/expired **mid-call** (e.g. it expired between server startup
  and this call) → the underlying `amazon-orders` call raises; the tool wrapper catches
  it and raises `fastmcp.exceptions.ToolError` with a message pointing the user to
  `uv run python scripts/amazon_login.py` (server restart required to pick up the
  refreshed session, since `login()` only runs once at startup).
- YNAB API failures continue to go through the existing `translate_api_exception`
  helper, reused as-is.

## `server.py` change

```python
amazon_settings = AmazonSettings.from_env()
if amazon_settings is not None:
    amazon_session = build_amazon_session(amazon_settings)
    try:
        amazon_session.login()
    except AmazonOrdersError as exc:
        print(f"Amazon session unavailable, skipping: {exc}", file=sys.stderr)
    else:
        amazon_orders_client = build_amazon_orders(amazon_session)
        amazon_transactions_client = build_amazon_transactions(amazon_session)
        find_amazon_transactions.register(
            mcp, client, amazon_transactions_client, amazon_orders_client, settings
        )
```

(Updated per the "Correction from live testing" note above — the original design didn't
call `login()` here at all.)

Conditional registration mirrors the existing `list-budgets` pattern (registered only
when no default budget is configured) — same shape, different condition.

## Dependencies

`pyproject.toml` gains `amazon-orders[browser]` in `[project.dependencies]` — the
`[browser]` extra (pulling in `playwright`) is required, not optional, since real
Amazon logins routinely need it to solve JavaScript-based challenges (see the
"Correction from live testing" note above).

## Testing strategy

- **`tests/test_amazon_matching.py`** — the acceptance criteria's required coverage:
  exact match, near-date match, split-shipment (multi-leg order), ambiguous tie, and
  no-match, all via plain fixture dataclasses. Zero mocking, zero network — pure
  function in, structured result out.
- **`tests/test_tools_find_amazon_transactions.py`** — thinner tests mocking the YNAB
  client and the two Amazon clients, following `test_tools_transactions.py`'s existing
  style: verifies the tool wraps `list_transactions()` + the Amazon clients +
  `match_transactions()` correctly and shapes the JSON-able output.
- **`tests/test_config.py`** additions for `AmazonSettings.from_env()` — present vs.
  absent env vars.
- No live Amazon calls in unit tests, per the acceptance criteria. `scripts/amazon_login.py`
  and any live-session verification remain manual/E2E-adjacent, exercised by the user
  during the Step 7b live-E2E handoff, not by `make tests`.

## Out of scope (confirmed)

- Automatically applying a categorization from a match — pairs with card #12.
- Configurable amount tolerance — unnecessary once matching against `Transaction
  .grand_total` (the actual charge amount) rather than `Order.grand_total`.
- Whole Foods order matching — excluded per product decision (already categorized
  differently in YNAB; out of this card's scope to reconcile).
