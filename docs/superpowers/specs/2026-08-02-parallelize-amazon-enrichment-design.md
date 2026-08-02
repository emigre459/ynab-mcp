# Parallelize find-amazon-transactions' Per-Order Enrichment Fetches — Design

**Issue:** [#20](https://github.com/emigre459/ynab-mcp/issues/20) — Parallelize find-amazon-transactions' per-order enrichment fetches
**Parent epic:** [#10](https://github.com/emigre459/ynab-mcp/issues/10) — AI-driven budget coaching & categorization for parents' YNAB budget (child 7 of 7 — the last remaining child)

## Why

Live testing of `find-amazon-transactions` (#15) showed a real run with ~47 matched orders (no split-shipment repeats) took multiple minutes. Root cause: `_order_for()` in `src/ynab_mcp/tools/find_amazon_transactions.py` calls `AmazonOrders.get_order(order_number)` once per *distinct* matched order, strictly sequentially, to fetch item-title detail for the reasoning text. `amazon-orders` is an unofficial HTML-scraping library, not a fast REST API — each call is a real scraped-page fetch + parse, so wall-clock time scales linearly with the number of distinct matched orders. `orders_cache` already dedupes repeated fetches for split-shipment orders, but provides zero savings when there are no repeats (the common case).

This is a pure performance fix — output shape and behavior are otherwise identical to today. Reducing the *number* of enrichment calls (e.g. skipping item-detail enrichment) is explicitly out of scope; the fix is making the necessary calls faster via bounded concurrency, not fewer.

## Constraint: session thread-safety

The single `AmazonSession` built at server startup (`amazon_client.py`'s `build_amazon_session`, called once in `server.py`) wraps one `requests.Session` instance, reused for the server's whole process lifetime. `requests.Session` has a documented caveat: concurrent requests that read/write `session.cookies` can race, and Amazon's page responses may rotate cookies/tokens even on routine authenticated fetches — this needed explicit verification, not an assumption of safety.

Confirmed via the installed `amazon-orders` library: cookies persist to a shared, file-locked location (`cookies_file_lock` guards all read/write access in `session.py`), and `AmazonSession.login()` fast-paths — a single cheap validity-check request, no interactive challenge — when valid persisted cookies already exist (this is exactly the mechanism `amazon_client.py`'s docstring already documents for the startup login).

## Architecture

A fresh `ThreadPoolExecutor(max_workers=3)` is created inside `find_amazon_transactions()` per call. Each of the 3 worker threads lazily constructs its own independent `AmazonOrders` client (backed by its own `AmazonSession`/`requests.Session`) on its *first* assigned task, via `threading.local()` — then reuses that same client for every subsequent order-fetch task the executor assigns to that thread within the same call.

This guarantees, by construction, that no two threads ever share a session concurrently: `threading.local()` storage is private per physical thread, and a single thread only ever does one thing at a time. This was chosen over two alternatives:

- **Share the single `AmazonSession`, lock around each `get_order` call** — simplest, but serializes the actual network calls (only one in-flight scrape at a time), defeating the purpose entirely.
- **Pre-build N independent clients, round-robin-assign order numbers to them before submission** — rejected as subtly incorrect: `ThreadPoolExecutor` doesn't preserve "one task per client-affinity slot" scheduling: with `max_workers=3` and 3 pre-built clients each assigned ~2 tasks, the executor could still run two tasks bound to the *same* pre-built client on two *different* threads simultaneously, since round-robin *assignment* doesn't guarantee round-robin *execution order*. Thread-local lazy construction avoids this entirely by tying client ownership to the physical worker thread itself, not to a pre-assignment scheme.

The executor and its thread-local storage are created fresh per call rather than persisted server-wide — simpler to reason about and test, and the extra cost (up to 3 one-time fast-path logins per call, each a single cheap request, not full interactive auth) is small relative to the wall-clock savings from parallelizing potentially dozens of scraped-page fetches.

## Session construction & wiring

A new function in `amazon_client.py`:

```python
def build_worker_amazon_orders(settings: AmazonSettings) -> AmazonOrders:
    """Construct a fresh, independently-authenticated AmazonOrders client.

    Unlike build_amazon_session/build_amazon_orders (used once at server
    startup for the primary session), this builds a brand-new AmazonSession
    each call and logs it in immediately -- intended for worker-thread-local
    use in find_amazon_transactions' concurrent enrichment fetches, where
    each worker thread needs its own independent requests.Session to avoid
    any risk of concurrent cookie-jar access on a shared session. The login
    call fast-paths (a single cheap request, no interactive challenge) since
    valid persisted cookies already exist from the server's own startup
    login.
    """
    session = build_amazon_session(settings)
    try:
        session.login()
    except AmazonOrdersError as exc:
        raise translate_amazon_exception(exc) from exc
    return build_amazon_orders(session)
```

`server.py`'s existing startup flow — build the main session, call `.login()`, gate tool registration on success — stays exactly as-is; that check is unrelated to this issue. What changes: instead of building and passing a single pre-built `amazon_orders_client` into `register()`, `server.py` passes a zero-arg factory:

```python
amazon_orders_client_factory = functools.partial(build_worker_amazon_orders, amazon_settings)
find_amazon_transactions.register(
    mcp, client, amazon_transactions_client, amazon_orders_client_factory, settings
)
```

`amazon_transactions_client` (used once per call for the bulk transaction-history fetch — `amazon_transactions_client.get_transactions(...)`, unaffected by this issue) stays built from the original main session, unchanged. `register()`'s and `find_amazon_transactions()`'s parameter `amazon_orders_client: AmazonOrders` is renamed and retyped to `amazon_orders_client_factory: Callable[[], AmazonOrders]`.

## Concurrent dispatch logic

Replace the sequential `_order_for`/`orders_cache` pattern in `find_amazon_transactions()`:

```python
distinct_order_numbers = {
    amazon_by_ref[m.amazon_transaction_ref].order_number
    for m in result.matches
    if amazon_by_ref[m.amazon_transaction_ref].order_number
}  # preserves today's blank-order-number skip + cross-match dedup

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

_MAX_ENRICHMENT_WORKERS = 3

with ThreadPoolExecutor(max_workers=_MAX_ENRICHMENT_WORKERS) as executor:
    order_futures = {
        order_number: executor.submit(_fetch_order, order_number)
        for order_number in distinct_order_numbers
    }
```

The existing `for match in result.matches:` loop changes only its one line: `order = order_futures[real_order_number].result() if real_order_number else None`.

**Failure handling — fail-fast, unchanged from today.** `.result()` re-raises the translated exception if that particular fetch failed, propagating out of the `for match in result.matches:` loop exactly as `_order_for`'s direct call does today — a single order's enrichment failure still aborts the entire tool call with the real translated error, matching current behavior exactly (`ThreadPoolExecutor`'s context manager waits for all submitted work to finish, successful or not, before the `with` block exits, so no dangling threads or unhandled background exceptions). This was an explicit design choice, not an oversight: graceful per-order degradation (returning partial results when one enrichment fails) was considered and rejected as a real behavior change beyond "pure performance fix."

**Correct attribution is guaranteed by construction, not by timing.** Each match looks up *its own* order's future by `order_number` in the `order_futures` dict — never a different one — so there is no code path by which one order's fetched detail could be attributed to a different match, regardless of completion order or thread scheduling.

## Testing

New tests in `tests/test_tools_find_amazon_transactions.py`:

- **Correct attribution** — attribution correctness is about `order_futures` dict keying, not about which physical client served a request, so a single shared `Mock()` client is sufficient: the factory returns that one mock for every thread, and `get_order`'s `side_effect` is a function keyed by its `order_number` argument (e.g. a dict lookup returning distinct fake `Order` objects per number). Run with several distinct matched orders and assert each match's `reasoning`/enrichment reflects its *own* order's items, not a neighbor's.
- **Genuine concurrency proof (non-flaky)** — use a `threading.Barrier(2)` inside a mocked `get_order` so at least 2 fetches must rendezvous before either can proceed, deterministically proving true concurrent execution rather than relying on a timing threshold (which would be flaky under CI load variance).
- **One failure aborts cleanly** — mock one specific order's fetch to raise `AmazonOrdersError`, others to succeed; assert `find_amazon_transactions` raises the correctly-translated `ToolError` (matching the failing order, via `translate_amazon_exception`) and that the call does not hang.
- **Thread-local session reuse** — mock the factory with a call-counting `Mock`; run with e.g. 10 distinct matched orders and assert the factory was called at most `_MAX_ENRICHMENT_WORKERS` (3) times, not once per order — proving sessions are constructed once per worker thread and reused, not rebuilt per fetch.
- **Output shape unchanged** — existing tests asserting `find_amazon_transactions`' output structure (`matches`/`ambiguous`/`unmatched` shape, reasoning text format, split-shipment grouping) must continue passing with only the internal fetch mechanism's mocking updated from a single `amazon_orders_client` to the new factory pattern.

New tests in `tests/test_amazon_client.py` for `build_worker_amazon_orders`: constructs a session, calls `.login()`, returns an `AmazonOrders` client wrapping it; a login failure raises the translated `ToolError` via `translate_amazon_exception`.

## Out of scope

- Reducing the number of enrichment calls (e.g. skipping item-detail enrichment) — explicitly out of scope per the issue; this is a "faster, not fewer" fix.
- A configurable worker-pool size (env var or tool parameter) — `_MAX_ENRICHMENT_WORKERS = 3` is a hardcoded conservative constant, confirmed with the user during the read-back gate.
- A persistent, server-lifetime thread pool or worker-session cache spanning multiple tool calls — the executor and its thread-local storage are scoped to a single `find_amazon_transactions()` call.
- Graceful per-order degradation on enrichment failure — confirmed during brainstorming as a real behavior change beyond this issue's "pure performance fix" framing; fail-fast is preserved exactly.
