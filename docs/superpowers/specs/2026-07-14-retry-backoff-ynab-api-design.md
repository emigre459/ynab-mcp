# Retry/Backoff for Transient YNAB API Failures — Design

**Issue:** [#17](https://github.com/emigre459/ynab-mcp/issues/17) — Add retry/backoff for transient YNAB API failures
**Parent epic:** [#10](https://github.com/emigre459/ynab-mcp/issues/10) — AI-driven budget coaching & categorization for parents' YNAB budget

## Why

A live 429 (rate-limit) hit during testing of the payee-lookup tool (#14) exposed a gap: no tool module or `client.py`/`errors.py` retries or backs off on transient failures (429, 5xx). Any tool that fans out into multiple API calls — or simply runs during a busy dev loop — can fail outright on a blip a short backoff would ride out.

The issue was amended twice (2026-07-13) after two more live 429s during testing of `find_amazon_transactions` (#15) and a related exposure noticed in `analyze-category-trends`/`spend_analysis.py` (#13), both since merged to `main`. The acceptance criteria now names all of `accounts`, `budgets`, `categories`, `lookup`, `months`, `payees`, `transactions`, `payee_patterns`, `find_amazon_transactions`, and `spend_analysis`.

**Confirmed constraint:** YNAB enforces a rolling 200-requests/hour window per access token, and — notably — omits the `X-Rate-Limit` header entirely on 429 responses (no `Retry-After` to key off either). This means backoff is a mitigation for transient bursts and 5xx blips, not a guarantee against a genuinely exhausted hourly quota (which can take up to an hour to clear on its own). The design below is scoped accordingly: short, bounded retries that fail fast with the real YNAB error once exhausted, rather than long waits that hang a tool call.

**Also in scope:** while auditing call patterns for this issue, `find_payee_transactions` in `payee_patterns.py` was found to call `list_transactions` once *per matched payee* — under fuzzy matching this can multiply a single tool call into many API requests, directly feeding the same rate-limit exposure this issue exists to fix. Its fix is folded into this issue rather than deferred, since it's the same underlying problem (unnecessary API call volume against the 200/hour budget).

## Architecture: shared retry helper in `client.py`

A single function, `call_with_retry`, wraps any zero-arg callable with `tenacity`-based retry logic:

```python
import tenacity

_MAX_ATTEMPTS = 3
_BACKOFF_INITIAL_SECONDS = 1
_BACKOFF_MAX_SECONDS = 8

_wait = tenacity.wait_exponential_jitter(initial=_BACKOFF_INITIAL_SECONDS, max=_BACKOFF_MAX_SECONDS)
_stop = tenacity.stop_after_attempt(_MAX_ATTEMPTS)


def _is_transient_ynab_error(exc: BaseException) -> bool:
    """True for a YNAB ApiException worth retrying: 429 or any 5xx."""
    return isinstance(exc, ynab.ApiException) and (
        exc.status == 429 or (exc.status is not None and 500 <= exc.status < 600)
    )


def call_with_retry(func: Callable[[], T]) -> T:
    """Call func(), retrying on transient YNAB API failures (429, 5xx).

    Non-transient failures (any other ynab.ApiException, or any other
    exception) propagate on the first attempt. Once retries are exhausted,
    the original exception propagates unchanged.
    """
    retrying = tenacity.Retrying(
        stop=_stop,
        wait=_wait,
        retry=tenacity.retry_if_exception(_is_transient_ynab_error),
        reraise=True,
    )
    return retrying(func)
```

`_wait` and `_stop` are module-level names (not inlined into `call_with_retry`) specifically so tests can monkeypatch `_wait` to `tenacity.wait_none()` and exercise real retry counts without real sleep delays.

`reraise=True` is the key integration point: once attempts are exhausted, `tenacity` re-raises the original `ynab.ApiException` rather than wrapping it in a `RetryError`. Every module's existing `except ynab.ApiException as exc: raise translate_api_exception(exc) from exc` therefore needs **no changes** — `translate_api_exception` keeps seeing exactly what it sees today, just after 1–3 attempts instead of always 1.

### Module coverage

**Direct edit (8 modules)** — each call site changes `response = api.get_x(...)` to `response = call_with_retry(lambda: api.get_x(...))`, wrapping only the network call, not the surrounding `.data.x` extraction or `try`/`except`:

- `accounts.py`, `budgets.py`, `categories.py`, `months.py`, `payees.py`, `transactions.py` — one call site each.
- `lookup.py` — 5 branches (account/category/payee/transaction/month), each currently a single chained expression (`ynab.AccountsApi(client).get_account_by_id(...).data.account`); each branch splits into `response = call_with_retry(lambda: ynab.AccountsApi(client).get_account_by_id(...)); result = response.data.account`.
- `spend_analysis.py` — one call site (`api.get_plan_month(...)`, invoked in a loop over the trailing-months window). No bulk alternative exists: `MonthsApi.get_plan_months` (plural) returns only budget-level `MonthSummary` totals, with no per-category breakdown, so it cannot replace the per-month `get_plan_month` (singular) calls this tool needs. Retry/backoff is the only available mitigation here.

**Covered via delegation (2 modules, no direct edit)** — both already call into `list_payees`/`list_transactions` rather than the SDK directly, so they inherit retry coverage automatically once those functions are wrapped:

- `payee_patterns.py` (`find_payee_transactions`) — calls `list_payees` and `list_transactions`.
- `find_amazon_transactions.py` — calls `list_transactions`.

## N+1 fix: `find_payee_transactions`

Current behavior: fetch all payees, match against the query, then call `list_transactions(client, budget_id, payee_id=...)` once per matched payee.

New behavior:

```python
payees = list_payees(client, budget_id)
matches = _match_payees(payees, payee_query, fuzzy_threshold)
if not matches:
    return []

all_transactions = list_transactions(client, budget_id)
transactions_by_payee_id: dict[str, list[ynab.TransactionDetail]] = defaultdict(list)
for transaction in all_transactions:
    if transaction.payee_id is not None:
        transactions_by_payee_id[str(transaction.payee_id)].append(transaction)

summaries: list[PayeeGroupSummary] = []
for matched in matches:
    transactions = transactions_by_payee_id.get(str(matched.payee.id), [])
    if not transactions:
        continue
    summaries.append(_summarize_group(matched, transactions))
return summaries
```

This drops the call count from `1 + N_matches` to a flat `2` (or `1` when there are zero matches — the unfiltered fetch is skipped entirely since there's nothing to look up), regardless of how many payees a fuzzy query matches. Output shape (`list[PayeeGroupSummary]`, one per matched payee with ≥1 transaction) is unchanged.

**Volume tradeoff:** both `get_transactions` (unfiltered) and `get_transactions_by_payee` default `since_date` to one year ago at the YNAB API level when unspecified — so the *time window* fetched is unchanged from today's per-payee behavior, not "all-time." But the batched call now returns the **whole budget's** year of activity in one response instead of just the matched payee's slice, which is a materially larger single payload for an account with heavy transaction volume (fewer requests, more data per request — the inherent tradeoff of batching). To give an explicit lever over this, `find_payee_transactions` gains optional `since_date`/`until_date` parameters (same names/semantics `list_transactions` already exposes), passed straight through to the single batched call:

```python
def find_payee_transactions(
    client: ynab.ApiClient,
    budget_id: str,
    payee_query: str,
    fuzzy_threshold: float = 0.6,
    since_date: date | None = None,
    until_date: date | None = None,
) -> list[PayeeGroupSummary]:
    ...
    all_transactions = list_transactions(
        client, budget_id, since_date=since_date, until_date=until_date
    )
```

Both default to `None` (YNAB's own 1-year default applies), and both are exposed on the `find-payee-transactions` MCP tool the same way `list-transactions` already exposes them — so a caller with an unusually large budget can narrow the window explicitly (e.g. `since_date="2026-01-01"`), trading recall for a smaller response.

## Rate-limit error enrichment (`errors.py`)

YNAB's actual 429 response body is minimal: `{"error": {"id": "429", "name": "too_many_requests", "detail": "Too many requests"}}` — `_extract_detail` would surface only the four words `"Too many requests"` today, which isn't enough for the calling agent to explain what happened or judge whether/when to retry. Once `call_with_retry`'s attempts are exhausted on a 429, `translate_api_exception` appends actionable context rather than relying on the raw detail alone:

```python
def translate_api_exception(exc: ynab.ApiException) -> ToolError:
    detail = _extract_detail(exc)
    logger.error("YNAB API request failed (status=%s): %s", exc.status, detail)
    if exc.status == 429:
        return ToolError(
            f"{detail} — YNAB rate limit exceeded (this access token allows 200 "
            "requests per rolling hour, and survived automatic retries already). "
            "The API does not report an exact reset time; the quota clears "
            "roughly one hour after the earliest request in the current window. "
            "Wait before retrying, or let the user know to try again in about an hour."
        )
    return ToolError(detail)
```

This keeps the real YNAB detail (satisfying the acceptance criterion) while giving the calling agent enough to produce a useful user-facing message and a concrete retry-timing estimate. **Explicitly out of scope:** the MCP server itself does not schedule a background retry job — a stdio tool call is synchronous request/response with no persistent scheduler or async push to the client, so any actual "wait and retry later" behavior is the calling agent/orchestrator's responsibility, informed by this message.

## Dependency

`tenacity` is a new runtime dependency (`uv add tenacity`), not currently in `pyproject.toml`.

## Testing

**`tests/test_client.py`** — core retry-logic tests, using a monkeypatched `_wait = tenacity.wait_none()` so retries run instantly:

- Transient 429 followed by success → returns the success result; underlying callable invoked more than once.
- Transient 5xx followed by success → same.
- Non-transient 4xx (e.g. 404) → fails on the first attempt; underlying callable invoked exactly once.
- Persistent transient failure (always 429) → exhausts `_MAX_ATTEMPTS` attempts, then re-raises the original `ynab.ApiException` unchanged (not a `tenacity.RetryError`).

**Each of the 8 directly-edited modules' existing test files** — one new wiring test per module confirming `call_with_retry` is actually invoked at that call site: a mocked transient failure followed by success still returns the correct data through the tool's plain function.

**`tests/test_tools_payee_patterns.py`** — new cases for the N+1 fix:

- Multiple matched payees → the mocked `list_transactions` is called exactly once (no `payee_id` filter), not once per match.
- Zero matched payees → the mocked `list_transactions` is never called.
- `since_date`/`until_date` passed to `find_payee_transactions` are forwarded to the single `list_transactions` call.

**`tests/test_errors.py`** — new case: a 429 `ApiException` produces a `ToolError` whose message includes both the raw YNAB detail and the rate-limit/retry-timing context; a non-429 `ApiException` (e.g. 404 or 500) is unaffected (message is exactly `_extract_detail`'s output, no enrichment appended).

## Blocked on #12 — do not finalize the implementation plan yet

**Issue #12 (Transaction & budget write tools) is being actively finished right now** (branch `12-write-tools`, 17 commits ahead of `main` as of this design, no PR open yet). Per explicit user decision, **this build pauses here** rather than proceeding to `writing-plans` — the same amendment pattern that already happened twice this session for #13/#15 (issue #17 gained new named modules mid-brainstorming when those merged) would very likely repeat for #12, since its four new write tools (`bulk-manage-transactions`, `manage-budgeted-amount`, `manage-payees`, `manage-scheduled-transaction`) will call the YNAB SDK directly and share the exact same rate-limit exposure this issue exists to fix.

**Resume trigger:** once `#12` merges to `main`, rebase this branch, re-audit `#12`'s new modules for their SDK call-site shape (same inspection done above for `spend_analysis.py`/`find_amazon_transactions.py`), fold them into the "Module coverage" section above, and re-run the spec self-review before moving to `writing-plans`. Do not skip straight to planning without this re-audit — a module added without inspection could have a call shape (e.g. a bulk/batch write endpoint) that doesn't fit the simple one-line `call_with_retry` wrap and needs its own judgment call, the same way `spend_analysis.py`'s lack of a bulk-months endpoint did.

## Out of scope (deferred, flagged to the user)

- Retry parameters (`_MAX_ATTEMPTS`, backoff bounds) are hardcoded module-level constants, not environment-configurable — no env var was requested, and the issue doesn't call for runtime tuning.
- Honoring a `Retry-After`-style header is not applicable — confirmed YNAB does not send one on 429 responses.
- Actual scheduling of a deferred retry once the rate limit clears — the MCP server surfaces enough information for the calling agent to do this itself; it does not implement a scheduler.
