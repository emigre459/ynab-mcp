# Parallelize Amazon Order-Enrichment Fetches Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `find-amazon-transactions`' sequential per-order enrichment fetches with bounded (3-worker) concurrent fetches, using thread-local independent Amazon sessions to avoid any shared-`requests.Session` race — a pure performance fix, per issue #20 and `docs/superpowers/specs/2026-08-02-parallelize-amazon-enrichment-design.md`.

**Architecture:** A new `build_worker_amazon_orders(settings)` factory in `amazon_client.py` constructs a fresh, independently-authenticated `AmazonOrders` client on demand. `find_amazon_transactions()` uses a fresh `ThreadPoolExecutor(max_workers=3)` per call; each worker thread lazily builds its own client via `threading.local()` on first use and reuses it for the rest of that call. One future per distinct non-blank order number, looked up by the existing per-match loop via `.result()` — fail-fast, identical error behavior to today.

**Tech Stack:** Python 3.13, `concurrent.futures.ThreadPoolExecutor`, `threading.local`, `amazon-orders` PyPI library, `pytest` + `pytest-mock`.

## Global Constraints

- `_MAX_ENRICHMENT_WORKERS = 3` — hardcoded conservative constant, no env var or tool parameter (confirmed during brainstorming).
- Fail-fast preserved exactly: a single order-fetch failure still aborts the entire `find_amazon_transactions()` call with the real translated error, matching today's sequential behavior. No graceful per-order degradation.
- Correct attribution must be guaranteed by construction (dict lookup by order number), not by timing.
- No two worker threads may ever share an `AmazonSession`/`requests.Session` concurrently — each worker thread gets its own, built via `threading.local()`.
- Output shape/behavior of `find_amazon_transactions()` must be otherwise identical to today — no new fields, no new tool parameters, no reduction in the number of enrichment calls.
- The executor and its thread-local storage are scoped to a single `find_amazon_transactions()` call, not persisted server-wide.

---

## Task 1: `build_worker_amazon_orders` factory in `amazon_client.py`

**Files:**
- Modify: `src/ynab_mcp/amazon_client.py`
- Test: `tests/test_amazon_client.py`

**Interfaces:**
- Produces: `build_worker_amazon_orders(settings: AmazonSettings) -> AmazonOrders`, importable from `ynab_mcp.amazon_client`. Raises `fastmcp.exceptions.ToolError` (via `translate_amazon_exception`) if login fails.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_amazon_client.py`. First add the new imports at the top of the file (replace the existing import block):

```python
"""Tests for ynab_mcp.amazon_client."""

from amazonorders.exception import AmazonOrdersAuthError
from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

from ynab_mcp.amazon_client import (
    build_amazon_orders,
    build_amazon_session,
    build_amazon_transactions,
    build_worker_amazon_orders,
)
from ynab_mcp.config import AmazonSettings
```

Then append these two tests at the end of the file:

```python
def test_build_worker_amazon_orders_logs_in_and_wraps_session(
    mocker: MockerFixture,
) -> None:
    """A fresh session is built, logged in, and wrapped in an AmazonOrders client."""
    session_cls = mocker.patch("ynab_mcp.amazon_client.AmazonSession")
    mocker.patch("ynab_mcp.amazon_client.AmazonOrdersConfig")
    orders_cls = mocker.patch("ynab_mcp.amazon_client.AmazonOrders")

    orders = build_worker_amazon_orders(_settings())

    session_cls.return_value.login.assert_called_once_with()
    orders_cls.assert_called_once_with(session_cls.return_value)
    assert orders is orders_cls.return_value


def test_build_worker_amazon_orders_translates_login_failure(
    mocker: MockerFixture,
) -> None:
    """A failed login surfaces as a ToolError with remediation, not a raw exception."""
    session_cls = mocker.patch("ynab_mcp.amazon_client.AmazonSession")
    mocker.patch("ynab_mcp.amazon_client.AmazonOrdersConfig")
    mocker.patch("ynab_mcp.amazon_client.AmazonOrders")
    session_cls.return_value.login.side_effect = AmazonOrdersAuthError("expired")

    with raises(ToolError, match="scripts/amazon_login.py"):
        build_worker_amazon_orders(_settings())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_amazon_client.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_worker_amazon_orders' from 'ynab_mcp.amazon_client'`.

- [ ] **Step 3: Implement `build_worker_amazon_orders`**

In `src/ynab_mcp/amazon_client.py`, add the import for `AmazonOrdersError` and `translate_amazon_exception` alongside the existing imports:

```python
from amazonorders.exception import AmazonOrdersError
from amazonorders.orders import AmazonOrders
from amazonorders.session import AmazonSession
from amazonorders.transactions import AmazonTransactions

from ynab_mcp.config import AmazonSettings
from ynab_mcp.errors import translate_amazon_exception
```

Then append this function at the end of the file, after `build_amazon_transactions`:

```python
def build_worker_amazon_orders(settings: AmazonSettings) -> AmazonOrders:
    """Construct a fresh, independently-authenticated ``AmazonOrders`` client.

    Unlike ``build_amazon_session``/``build_amazon_orders`` (used once at
    server startup for the primary, long-lived session), this builds a
    brand-new ``AmazonSession`` on every call and logs it in immediately.
    It exists for ``find_amazon_transactions``' concurrent enrichment
    fetches, where each worker thread needs its own independent
    ``requests.Session`` to avoid any risk of concurrent cookie-jar access
    on a session shared across threads. The login call fast-paths (a
    single cheap request, no interactive challenge) as long as valid
    persisted cookies already exist from the server's own startup login.

    Parameters
    ----------
    settings : AmazonSettings
        The server's parsed Amazon configuration.

    Returns
    -------
    amazonorders.orders.AmazonOrders
        A client backed by a freshly-authenticated, independent session.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If the login attempt fails (e.g. the persisted session has
        actually expired and a real interactive challenge would be
        required, which cannot complete inside a worker thread).
    """
    session = build_amazon_session(settings)
    try:
        session.login()
    except AmazonOrdersError as exc:
        raise translate_amazon_exception(exc) from exc
    return build_amazon_orders(session)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_amazon_client.py -v`
Expected: All 6 tests PASS (4 pre-existing + 2 new).

- [ ] **Step 5: Lint and type-check**

Run: `make lint`
Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add src/ynab_mcp/amazon_client.py tests/test_amazon_client.py
git commit -m "feat: add build_worker_amazon_orders factory for independent worker sessions"
```

---

## Task 2: Concurrent dispatch rewrite in `find_amazon_transactions.py`

**Files:**
- Modify: `src/ynab_mcp/tools/find_amazon_transactions.py`
- Test: `tests/test_tools_find_amazon_transactions.py`

**Interfaces:**
- Consumes: nothing from Task 1 directly (this task's tests use plain mock factories; the real `build_worker_amazon_orders` is wired in by Task 4).
- Produces: `find_amazon_transactions(ynab_client, amazon_transactions_client, amazon_orders_client_factory, budget_id, ...)` — the third positional parameter is renamed from `amazon_orders_client: AmazonOrders` to `amazon_orders_client_factory: Callable[[], AmazonOrders]`. `register(mcp, ynab_client, amazon_transactions_client, amazon_orders_client_factory, settings)` — same rename on its third Amazon-related parameter.

This task rewrites the dispatch mechanism and migrates all 9 pre-existing tests to the new factory-based calling convention. New concurrency-proving tests are added in Task 3.

- [ ] **Step 1: Update one existing test to the new calling convention (TDD RED for the new interface)**

In `tests/test_tools_find_amazon_transactions.py`, change `test_find_amazon_transactions_returns_exact_match_with_reasoning`'s call site from:

```python
    result = find_amazon_transactions(
        ynab_client, amazon_transactions_client, amazon_orders_client, "budget-1"
    )
```

to:

```python
    result = find_amazon_transactions(
        ynab_client,
        amazon_transactions_client,
        lambda: amazon_orders_client,
        "budget-1",
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tools_find_amazon_transactions.py::test_find_amazon_transactions_returns_exact_match_with_reasoning -v`
Expected: FAIL — the current code calls `amazon_orders_client.get_order(...)` directly, but `amazon_orders_client` is now a plain lambda (no `.get_order` attribute), so this raises `AttributeError: 'function' object has no attribute 'get_order'`.

- [ ] **Step 3: Implement the concurrent dispatch rewrite**

In `src/ynab_mcp/tools/find_amazon_transactions.py`, add these imports at the top (after the existing `from datetime import date` line):

```python
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date
```

Add the new module-level constant alongside the existing ones (after `_DEFAULT_LOOKBACK_DAYS`):

```python
_MAX_ENRICHMENT_WORKERS = 3
```

Change `find_amazon_transactions`'s signature (the `amazon_orders_client` parameter):

```python
def find_amazon_transactions(
    ynab_client: ynab.ApiClient,
    amazon_transactions_client: AmazonTransactions,
    amazon_orders_client_factory: Callable[[], AmazonOrders],
    budget_id: str,
    since_date: date | None = None,
    until_date: date | None = None,
    date_window_days: int = 3,
    include_approved: bool = False,
) -> dict[str, object]:
```

Update the docstring's `Parameters` section for that parameter:

```python
    amazon_orders_client_factory : Callable[[], amazonorders.orders.AmazonOrders]
        A zero-argument callable that constructs a fresh, independently-
        authenticated ``AmazonOrders`` client. Called at most once per
        concurrent worker thread (see below), not once per order -- each
        worker thread lazily builds and reuses its own client for the
        duration of this call.
```

Replace the `orders_cache`/`_order_for` block and the `matches_out` loop's order-fetching line. Replace:

```python
    orders_cache: dict[str, Order] = {}

    def _order_for(order_number: str) -> Order:
        if order_number not in orders_cache:
            try:
                orders_cache[order_number] = amazon_orders_client.get_order(
                    order_number
                )
            except AmazonOrdersError as exc:
                raise translate_amazon_exception(exc) from exc
        return orders_cache[order_number]

    matches_out: list[dict[str, object]] = []
    for match in result.matches:
        real_order_number = amazon_by_ref[match.amazon_transaction_ref].order_number
        order = _order_for(real_order_number) if real_order_number else None
```

with:

```python
    distinct_order_numbers = {
        amazon_by_ref[m.amazon_transaction_ref].order_number
        for m in result.matches
        if amazon_by_ref[m.amazon_transaction_ref].order_number
    }

    _thread_local = threading.local()

    def _worker_client() -> AmazonOrders:
        if not hasattr(_thread_local, "orders_client"):
            _thread_local.orders_client = amazon_orders_client_factory()
        return _thread_local.orders_client

    def _fetch_order(order_number: str) -> Order:
        try:
            return _worker_client().get_order(order_number)
        except AmazonOrdersError as exc:
            raise translate_amazon_exception(exc) from exc

    with ThreadPoolExecutor(max_workers=_MAX_ENRICHMENT_WORKERS) as executor:
        order_futures = {
            order_number: executor.submit(_fetch_order, order_number)
            for order_number in distinct_order_numbers
        }

    matches_out: list[dict[str, object]] = []
    for match in result.matches:
        real_order_number = amazon_by_ref[match.amazon_transaction_ref].order_number
        order = (
            order_futures[real_order_number].result() if real_order_number else None
        )
```

(the rest of the loop body -- building each `matches_out` entry -- is unchanged)

Finally, update `register()`'s signature and docstring the same way (its Amazon-orders parameter):

```python
def register(
    mcp: FastMCP,
    ynab_client: ynab.ApiClient,
    amazon_transactions_client: AmazonTransactions,
    amazon_orders_client_factory: Callable[[], AmazonOrders],
    settings: Settings,
) -> None:
```

```python
    amazon_orders_client_factory : Callable[[], amazonorders.orders.AmazonOrders]
        A zero-argument callable that constructs a fresh, independently-
        authenticated Amazon orders client, used for concurrent per-order
        enrichment fetches.
```

And its forwarding call inside `find_amazon_transactions_tool`:

```python
        return find_amazon_transactions(
            ynab_client,
            amazon_transactions_client,
            amazon_orders_client_factory,
            resolved_budget_id,
            since_date=since_date,
            until_date=until_date,
            date_window_days=date_window_days,
            include_approved=include_approved,
        )
```

- [ ] **Step 4: Run the one updated test to verify it passes**

Run: `uv run pytest tests/test_tools_find_amazon_transactions.py::test_find_amazon_transactions_returns_exact_match_with_reasoning -v`
Expected: PASS.

- [ ] **Step 5: Migrate the remaining 8 existing tests to the factory calling convention**

Each of these tests currently passes `amazon_orders_client` as the third positional argument to `find_amazon_transactions(...)`. Change each call site to pass `lambda: amazon_orders_client` instead (same pattern as Step 1). The 8 remaining call sites, each with `amazon_orders_client` currently as the third argument:

In `test_find_amazon_transactions_excludes_refunds_and_whole_foods`:
```python
    result = find_amazon_transactions(
        ynab_client,
        amazon_transactions_client,
        lambda: amazon_orders_client,
        "budget-1",
    )
```

In `test_find_amazon_transactions_ignores_non_amazon_payees`:
```python
    result = find_amazon_transactions(
        ynab_client,
        amazon_transactions_client,
        lambda: amazon_orders_client,
        "budget-1",
    )
```

In `test_find_amazon_transactions_surfaces_ambiguous_candidates`:
```python
    result = find_amazon_transactions(
        ynab_client,
        amazon_transactions_client,
        lambda: amazon_orders_client,
        "budget-1",
    )
```

In `test_find_amazon_transactions_matches_blank_order_numbers_without_enrichment`:
```python
    result = find_amazon_transactions(
        ynab_client,
        amazon_transactions_client,
        lambda: amazon_orders_client,
        "budget-1",
    )
```

In `test_find_amazon_transactions_does_not_fake_group_blank_order_numbers`:
```python
    result = find_amazon_transactions(
        ynab_client,
        amazon_transactions_client,
        lambda: amazon_orders_client,
        "budget-1",
    )
```

In `test_find_amazon_transactions_excludes_approved_by_default`:
```python
    result = find_amazon_transactions(
        ynab_client,
        amazon_transactions_client,
        lambda: amazon_orders_client,
        "budget-1",
    )
```

In `test_find_amazon_transactions_includes_approved_when_requested`:
```python
    result = find_amazon_transactions(
        ynab_client,
        amazon_transactions_client,
        lambda: amazon_orders_client,
        "budget-1",
        include_approved=True,
    )
```

In `test_find_amazon_transactions_translates_auth_error`:
```python
    with raises(ToolError, match="scripts/amazon_login.py"):
        find_amazon_transactions(
            ynab_client,
            amazon_transactions_client,
            lambda: amazon_orders_client,
            "budget-1",
        )
```

- [ ] **Step 6: Run the full test file to verify everything passes**

Run: `uv run pytest tests/test_tools_find_amazon_transactions.py -v`
Expected: All 9 tests PASS.

- [ ] **Step 7: Lint and type-check**

Run: `make lint`
Expected: No errors. If mypy flags `Order` or `AmazonOrders` as unused after the rewrite, confirm both are still referenced (`Order` in `_fetch_order`'s return type and `_build_reasoning`'s parameter; `AmazonOrders` in `_worker_client`'s return type and the new signature) -- they should still be used correctly.

- [ ] **Step 8: Commit**

```bash
git add src/ynab_mcp/tools/find_amazon_transactions.py tests/test_tools_find_amazon_transactions.py
git commit -m "feat: parallelize per-order enrichment fetches with thread-local sessions"
```

---

## Task 3: New concurrency-proving tests

**Files:**
- Test: `tests/test_tools_find_amazon_transactions.py`

**Interfaces:**
- Consumes: `find_amazon_transactions(ynab_client, amazon_transactions_client, amazon_orders_client_factory, budget_id, ...)` from Task 2, exactly as Task 2 left it.

Four new tests proving the concurrent-dispatch behavior itself, on top of Task 2's migrated existing tests (which prove output is otherwise unchanged).

- [ ] **Step 1: Write the failing tests**

Add this import at the top of `tests/test_tools_find_amazon_transactions.py` (alongside the existing ones):

```python
import threading
```

Append these four tests at the end of the file:

```python
def test_find_amazon_transactions_attributes_enrichment_to_correct_order(
    mocker: MockerFixture,
) -> None:
    """Each match's enrichment reflects its own order, never a neighbor's.

    A single shared mock client is sufficient here: attribution
    correctness comes from the order_futures dict keying in the
    implementation, not from which physical client served a request.
    """
    ynab_client = mocker.Mock()
    list_transactions = mocker.patch(
        "ynab_mcp.tools.find_amazon_transactions.list_transactions"
    )
    list_transactions.return_value = [
        _ynab_txn(mocker, "y1", -1000, date(2026, 6, 1), "Amazon.com"),
        _ynab_txn(mocker, "y2", -2000, date(2026, 6, 2), "Amazon.com"),
    ]
    amazon_transactions_client = mocker.Mock()
    amazon_transactions_client.get_transactions.return_value = [
        _amazon_txn("111-1111111", -10.00, date(2026, 6, 1)),
        _amazon_txn("222-2222222", -20.00, date(2026, 6, 2)),
    ]
    orders_by_number = {
        "111-1111111": _order(["First Widget"]),
        "222-2222222": _order(["Second Widget"]),
    }
    shared_client = mocker.Mock()
    shared_client.get_order.side_effect = lambda order_number: orders_by_number[
        order_number
    ]

    result = find_amazon_transactions(
        ynab_client,
        amazon_transactions_client,
        lambda: shared_client,
        "budget-1",
    )

    matches_by_order = {m["order_number"]: m for m in result["matches"]}  # type: ignore[union-attr]
    assert "First Widget" in matches_by_order["111-1111111"]["reasoning"]
    assert "Second Widget" in matches_by_order["222-2222222"]["reasoning"]


def test_find_amazon_transactions_fetches_orders_concurrently(
    mocker: MockerFixture,
) -> None:
    """At least two order fetches are genuinely in flight at the same time.

    A threading.Barrier forces two fetches to rendezvous before either can
    proceed -- deterministic proof of real concurrency, not a timing
    threshold (which would be flaky under CI load variance). If the
    fetches ran sequentially, the second call would never reach the
    barrier while the first is waiting, and the test would hang until
    pytest's timeout.
    """
    ynab_client = mocker.Mock()
    list_transactions = mocker.patch(
        "ynab_mcp.tools.find_amazon_transactions.list_transactions"
    )
    list_transactions.return_value = [
        _ynab_txn(mocker, "y1", -1000, date(2026, 6, 1), "Amazon.com"),
        _ynab_txn(mocker, "y2", -2000, date(2026, 6, 2), "Amazon.com"),
    ]
    amazon_transactions_client = mocker.Mock()
    amazon_transactions_client.get_transactions.return_value = [
        _amazon_txn("111-1111111", -10.00, date(2026, 6, 1)),
        _amazon_txn("222-2222222", -20.00, date(2026, 6, 2)),
    ]
    barrier = threading.Barrier(2, timeout=5)

    def _get_order(order_number: str) -> SimpleNamespace:
        barrier.wait()
        return _order(["Widget"])

    shared_client = mocker.Mock()
    shared_client.get_order.side_effect = _get_order

    result = find_amazon_transactions(
        ynab_client,
        amazon_transactions_client,
        lambda: shared_client,
        "budget-1",
    )

    assert len(result["matches"]) == 2  # type: ignore[arg-type]


def test_find_amazon_transactions_one_order_failure_aborts_cleanly(
    mocker: MockerFixture,
) -> None:
    """One failing order fetch aborts the whole call, matching today's behavior."""
    ynab_client = mocker.Mock()
    list_transactions = mocker.patch(
        "ynab_mcp.tools.find_amazon_transactions.list_transactions"
    )
    list_transactions.return_value = [
        _ynab_txn(mocker, "y1", -1000, date(2026, 6, 1), "Amazon.com"),
        _ynab_txn(mocker, "y2", -2000, date(2026, 6, 2), "Amazon.com"),
    ]
    amazon_transactions_client = mocker.Mock()
    amazon_transactions_client.get_transactions.return_value = [
        _amazon_txn("111-1111111", -10.00, date(2026, 6, 1)),
        _amazon_txn("222-2222222", -20.00, date(2026, 6, 2)),
    ]

    def _get_order(order_number: str) -> SimpleNamespace:
        if order_number == "222-2222222":
            raise AmazonOrdersAuthError("expired mid-run")
        return _order(["Widget"])

    shared_client = mocker.Mock()
    shared_client.get_order.side_effect = _get_order

    with raises(ToolError, match="scripts/amazon_login.py"):
        find_amazon_transactions(
            ynab_client,
            amazon_transactions_client,
            lambda: shared_client,
            "budget-1",
        )


def test_find_amazon_transactions_reuses_worker_sessions_across_orders(
    mocker: MockerFixture,
) -> None:
    """The factory is called at most once per worker thread, not once per order.

    10 distinct orders with a 3-worker pool should call the factory at
    most 3 times -- proving sessions are built once per worker thread and
    reused, not rebuilt per fetch.
    """
    ynab_client = mocker.Mock()
    list_transactions = mocker.patch(
        "ynab_mcp.tools.find_amazon_transactions.list_transactions"
    )
    list_transactions.return_value = [
        _ynab_txn(mocker, f"y{i}", -1000 * i, date(2026, 6, i), "Amazon.com")
        for i in range(1, 11)
    ]
    amazon_transactions_client = mocker.Mock()
    amazon_transactions_client.get_transactions.return_value = [
        _amazon_txn(f"11{i}-1111111", -10.00 * i, date(2026, 6, i))
        for i in range(1, 11)
    ]

    def _client_factory() -> Mock:
        client = mocker.Mock()
        client.get_order.side_effect = lambda order_number: _order(["Widget"])
        return client

    factory = mocker.Mock(side_effect=_client_factory)

    result = find_amazon_transactions(
        ynab_client,
        amazon_transactions_client,
        factory,
        "budget-1",
    )

    assert len(result["matches"]) == 10  # type: ignore[arg-type]
    assert factory.call_count <= 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_find_amazon_transactions.py -k "attributes_enrichment_to_correct_order or fetches_orders_concurrently or one_order_failure_aborts_cleanly or reuses_worker_sessions_across_orders" -v`
Expected: These 4 tests should already PASS if Task 2's implementation is correct (this task adds coverage, it doesn't change behavior) -- if any FAIL, that reveals a real gap in Task 2's dispatch logic (e.g. the concurrency test hanging means fetches aren't actually running in parallel; the attribution test failing means the dict-keying logic has a bug). Treat any failure here as a Task 2 defect to fix, not something to work around in the test.

- [ ] **Step 3: Fix any Task 2 gaps the new tests reveal (only if needed)**

If Step 2 revealed a real gap, fix it in `src/ynab_mcp/tools/find_amazon_transactions.py` per the design in Task 2's Step 3 -- do not weaken these tests to make them pass.

- [ ] **Step 4: Run the full test file to verify everything passes**

Run: `uv run pytest tests/test_tools_find_amazon_transactions.py -v`
Expected: All 13 tests PASS (9 from Task 2 + 4 new).

- [ ] **Step 5: Lint and type-check**

Run: `make lint`

- [ ] **Step 6: Commit**

```bash
git add tests/test_tools_find_amazon_transactions.py
git commit -m "test: prove concurrent enrichment dispatch is correct and race-free"
```

---

## Task 4: `server.py` wiring

**Files:**
- Modify: `src/ynab_mcp/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `build_worker_amazon_orders(settings: AmazonSettings) -> AmazonOrders` from Task 1. `find_amazon_transactions.register(mcp, ynab_client, amazon_transactions_client, amazon_orders_client_factory, settings)` from Task 2.

- [ ] **Step 1: Update the failing tests first**

In `tests/test_server.py`, remove the now-stale `mocker.patch("ynab_mcp.server.build_amazon_orders")` line from both `test_build_server_registers_find_amazon_transactions_when_configured` and `test_build_server_omits_find_amazon_transactions_when_login_fails` (server.py will no longer call `build_amazon_orders` directly, so patching it is meaningless and the patch target would silently no-op).

In `test_build_server_registers_find_amazon_transactions_when_configured`, change:

```python
    build_amazon_session = mocker.patch("ynab_mcp.server.build_amazon_session")
    mocker.patch("ynab_mcp.server.build_amazon_orders")
    mocker.patch("ynab_mcp.server.build_amazon_transactions")
```

to:

```python
    build_amazon_session = mocker.patch("ynab_mcp.server.build_amazon_session")
    mocker.patch("ynab_mcp.server.build_amazon_transactions")
```

In `test_build_server_omits_find_amazon_transactions_when_login_fails`, change:

```python
    build_amazon_session = mocker.patch("ynab_mcp.server.build_amazon_session")
    build_amazon_session.return_value.login.side_effect = AmazonOrdersAuthError(
        "session expired"
    )
    mocker.patch("ynab_mcp.server.build_amazon_orders")
    mocker.patch("ynab_mcp.server.build_amazon_transactions")
```

to:

```python
    build_amazon_session = mocker.patch("ynab_mcp.server.build_amazon_session")
    build_amazon_session.return_value.login.side_effect = AmazonOrdersAuthError(
        "session expired"
    )
    mocker.patch("ynab_mcp.server.build_amazon_transactions")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_server.py -k "find_amazon_transactions" -v`
Expected: FAIL -- `AttributeError` or import error, since `ynab_mcp.server` still imports and calls `build_amazon_orders` at this point (server.py hasn't been updated yet), so removing the mock leaves the real `build_amazon_orders(amazon_session)` call running against a mocked `AmazonSession` class, which will likely fail differently (e.g. `AmazonOrders(session_cls.return_value)` succeeding trivially, or `find_amazon_transactions.register`'s new required-factory signature not yet being satisfied since server.py hasn't changed). Treat any failure here as expected RED for this step; the real signal is Step 4's GREEN.

- [ ] **Step 3: Implement the wiring change**

In `src/ynab_mcp/server.py`, change the import block:

```python
from ynab_mcp.amazon_client import (
    build_amazon_session,
    build_amazon_transactions,
    build_worker_amazon_orders,
)
```

Add `functools` to the top-level imports:

```python
import functools
import sys
```

Replace the Amazon wiring block inside `build_server()`:

```python
    amazon_settings = AmazonSettings.from_env()
    if amazon_settings is not None:
        amazon_session = build_amazon_session(amazon_settings)
        try:
            amazon_session.login()
        except AmazonOrdersError as exc:
            print(
                f"Amazon session unavailable, find-amazon-transactions will not be "
                f"registered this run: {exc} Run "
                "`uv run python scripts/amazon_login.py` to re-establish it.",
                file=sys.stderr,
            )
        else:
            amazon_transactions_client = build_amazon_transactions(amazon_session)
            amazon_orders_client_factory = functools.partial(
                build_worker_amazon_orders, amazon_settings
            )
            find_amazon_transactions.register(
                mcp,
                client,
                amazon_transactions_client,
                amazon_orders_client_factory,
                settings,
            )
```

(only the `else` branch's body changes -- the `try`/`except` startup login-validation logic stays exactly as-is)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_server.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Run the full suite**

Run: `make tests`
Expected: All tests pass, no regressions.

- [ ] **Step 6: Lint and type-check**

Run: `make lint`
Expected: No errors.

- [ ] **Step 7: Commit**

```bash
git add src/ynab_mcp/server.py tests/test_server.py
git commit -m "feat: wire independent worker-session factory into find-amazon-transactions"
```

---

## Task 5: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `make tests`
Expected: All tests pass (existing suite + all new tests from Tasks 1-4).

- [ ] **Step 2: Run lint and type-check**

Run: `make lint`
Expected: No errors.

- [ ] **Step 3: Run the coverage gate**

Run: `make coverage`
Expected: Passes the 80% threshold.

- [ ] **Step 4: Confirm no leftover sequential fetch code**

Run: `grep -n "orders_cache\|_order_for" src/ynab_mcp/tools/find_amazon_transactions.py`
Expected: No matches -- the old sequential pattern was fully replaced, not left dead alongside the new one.

This task has no code changes and no commit -- it's the final gate before build-from-issue's own Step 6 (project E2E) and Step 7 (acceptance-criteria audit) run.
