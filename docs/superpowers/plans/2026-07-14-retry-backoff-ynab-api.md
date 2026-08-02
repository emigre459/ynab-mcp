# Retry/Backoff for Transient YNAB API Failures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add retry/backoff for transient YNAB API failures (429, 5xx) across all 14 tool modules, fix the N+1 API-call pattern in `find_payee_transactions`, and enrich rate-limit error messages -- per issue #17 and `docs/superpowers/specs/2026-07-14-retry-backoff-ynab-api-design.md`.

**Architecture:** A single `call_with_retry(func, *, include_5xx=True)` helper in `client.py`, built on `tenacity.Retrying`, wraps each YNAB SDK call site in place (`response = api.get_x(...)` becomes `response = call_with_retry(lambda: api.get_x(...))`). `include_5xx=False` is passed only at the two non-idempotent create-transaction call sites, where a 5xx is ambiguous about whether the write already landed. `payee_patterns.py`'s `find_payee_transactions` is restructured to fetch all budget transactions once instead of once per matched payee, with an optional `since_date`/`until_date` override. `errors.py` gains 429-specific guidance for the calling agent.

**Tech Stack:** Python 3.13, `tenacity` (new dependency), `ynab` SDK v4.2.0, `fastmcp` v3, `pytest` + `pytest-mock`.

## Global Constraints

- `_MAX_ATTEMPTS = 3`, exponential-jitter backoff from 1s to a cap of 8s (`tenacity.wait_exponential_jitter(initial=1, max=8)`), per the approved spec.
- 429 is always retryable (gateway-level rejection, no write occurred). 5xx is retryable only when `include_5xx=True` (the default) -- the two `create_transaction`/`create_scheduled_transaction` call sites pass `include_5xx=False` since a 5xx there is ambiguous about whether the write landed.
- `reraise=True` on every `tenacity.Retrying` call: once attempts are exhausted, the original `ynab.ApiException` propagates unchanged so every module's existing `except ynab.ApiException as exc: raise translate_api_exception(exc) from exc` needs no changes.
- `_wait`/`_stop` are module-level names in `ynab_mcp.client` (not inlined) so tests can `mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())` and run retries instantly.
- Wrap only the network call itself (the line that can raise `ynab.ApiException`), never the surrounding `try`/`except` or `.data.x` extraction.
- No behavior change to what any tool returns on success; no new environment variables; no change to `translate_api_exception`'s non-429 behavior.

---

## Task 1: `call_with_retry` helper in `client.py`

**Files:**
- Modify: `pyproject.toml` (add `tenacity` dependency)
- Modify: `src/ynab_mcp/client.py`
- Test: `tests/test_client.py`

**Interfaces:**
- Produces: `call_with_retry(func: Callable[[], T], *, include_5xx: bool = True) -> T`, importable from `ynab_mcp.client`. Module-level `_wait` and `_stop` names in `ynab_mcp.client`, for test monkeypatching.

- [ ] **Step 1: Add the `tenacity` dependency**

Run: `uv add tenacity`

Expected: `pyproject.toml`'s `dependencies` list gains a `tenacity>=...` line and `uv.lock` updates.

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_client.py` (add `import tenacity` and `import ynab` to the existing imports, then add these tests at the end of the file):

```python
import tenacity
import ynab

from ynab_mcp.client import call_with_retry


def test_call_with_retry_succeeds_after_transient_429(mocker: MockerFixture) -> None:
    """A 429 followed by success returns the success result."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    func = mocker.Mock(
        side_effect=[
            ynab.ApiException(status=429, reason="Too Many Requests", body=None),
            "ok",
        ]
    )

    result = call_with_retry(func)

    assert result == "ok"
    assert func.call_count == 2


def test_call_with_retry_succeeds_after_transient_5xx(mocker: MockerFixture) -> None:
    """A 5xx followed by success returns the success result (default include_5xx=True)."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    func = mocker.Mock(
        side_effect=[
            ynab.ApiException(status=503, reason="Service Unavailable", body=None),
            "ok",
        ]
    )

    result = call_with_retry(func)

    assert result == "ok"
    assert func.call_count == 2


def test_call_with_retry_include_5xx_false_still_retries_429(
    mocker: MockerFixture,
) -> None:
    """include_5xx=False still retries a 429 -- only 5xx is excluded."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    func = mocker.Mock(
        side_effect=[
            ynab.ApiException(status=429, reason="Too Many Requests", body=None),
            "ok",
        ]
    )

    result = call_with_retry(func, include_5xx=False)

    assert result == "ok"
    assert func.call_count == 2


def test_call_with_retry_include_5xx_false_does_not_retry_5xx(
    mocker: MockerFixture,
) -> None:
    """include_5xx=False fails immediately on a 5xx -- no retry, no duplicate risk."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    exc = ynab.ApiException(status=500, reason="Internal Server Error", body=None)
    func = mocker.Mock(side_effect=[exc, "ok"])

    with pytest.raises(ynab.ApiException) as exc_info:
        call_with_retry(func, include_5xx=False)

    assert exc_info.value.status == 500
    assert func.call_count == 1


def test_call_with_retry_does_not_retry_non_transient_4xx(
    mocker: MockerFixture,
) -> None:
    """A non-429 4xx (e.g. 404) fails on the first attempt, never retried."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    exc = ynab.ApiException(status=404, reason="Not Found", body=None)
    func = mocker.Mock(side_effect=exc)

    with pytest.raises(ynab.ApiException) as exc_info:
        call_with_retry(func)

    assert exc_info.value.status == 404
    assert func.call_count == 1


def test_call_with_retry_exhausts_attempts_and_reraises(
    mocker: MockerFixture,
) -> None:
    """A persistent 429 exhausts _MAX_ATTEMPTS then re-raises the real exception."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    exc = ynab.ApiException(status=429, reason="Too Many Requests", body=None)
    func = mocker.Mock(side_effect=exc)

    with pytest.raises(ynab.ApiException) as exc_info:
        call_with_retry(func)

    assert exc_info.value.status == 429
    assert func.call_count == 3
```

Also add `import pytest` to the top of `tests/test_client.py` if not already present (it currently imports only `pytest` for `pytest.raises` -- check the existing `import pytest` line at the top of the file and keep it; do not duplicate).

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_client.py -v`
Expected: FAIL with `ImportError: cannot import name 'call_with_retry' from 'ynab_mcp.client'` (or `AttributeError` on `ynab_mcp.client._wait`).

- [ ] **Step 4: Implement `call_with_retry` in `client.py`**

Replace the full contents of `src/ynab_mcp/client.py` with:

```python
"""YNAB API client construction and budget-id resolution."""

from collections.abc import Callable
from typing import TypeVar

import tenacity
import ynab
from fastmcp.exceptions import ToolError

from ynab_mcp.config import Settings

T = TypeVar("T")

_MAX_ATTEMPTS = 3
_BACKOFF_INITIAL_SECONDS = 1
_BACKOFF_MAX_SECONDS = 8

_wait = tenacity.wait_exponential_jitter(
    initial=_BACKOFF_INITIAL_SECONDS, max=_BACKOFF_MAX_SECONDS
)
_stop = tenacity.stop_after_attempt(_MAX_ATTEMPTS)


def build_api_client(settings: Settings) -> ynab.ApiClient:
    """Construct a YNAB ``ApiClient`` from server settings.

    Parameters
    ----------
    settings : Settings
        The server's parsed configuration; only ``ynab_pat`` is used.

    Returns
    -------
    ynab.ApiClient
        A configured API client, reused for the server's process lifetime.
    """
    configuration = ynab.Configuration(access_token=settings.ynab_pat)
    return ynab.ApiClient(configuration)


def resolve_budget_id(budget_id: str | None, settings: Settings) -> str:
    """Resolve an explicit or default YNAB budget id.

    Parameters
    ----------
    budget_id : str | None
        A budget id explicitly supplied by the caller, or ``None`` to fall
        back to the configured default.
    settings : Settings
        The server's parsed configuration, used for its
        ``ynab_default_budget_id`` fallback.

    Returns
    -------
    str
        The budget id to use for the API call.

    Raises
    ------
    ToolError
        If ``budget_id`` is ``None`` and no default budget is configured.
    """
    if budget_id is not None:
        return budget_id
    if settings.ynab_default_budget_id is not None:
        return settings.ynab_default_budget_id
    raise ToolError(
        "No budget_id provided and YNAB_DEFAULT_BUDGET_ID is not configured."
    )


def require_writable(settings: Settings) -> None:
    """Guard a write tool against ``YNAB_READ_ONLY``.

    Parameters
    ----------
    settings : Settings
        The server's parsed configuration.

    Raises
    ------
    ToolError
        If ``settings.ynab_read_only`` is ``True``.
    """
    if settings.ynab_read_only:
        raise ToolError("YNAB_READ_ONLY is enabled; write operations are disabled.")


def _is_transient_ynab_error(exc: BaseException, *, include_5xx: bool) -> bool:
    """True for a YNAB ApiException worth retrying.

    429 is always retryable -- a rate-limit rejection happens at the
    gateway, before any application logic runs, so nothing was written.
    5xx is only retryable when ``include_5xx`` is True -- some call sites
    (non-idempotent creates) pass False since a 5xx there is ambiguous
    about whether the write already landed.

    Parameters
    ----------
    exc : BaseException
        The exception raised by the wrapped call.
    include_5xx : bool
        Whether a 5xx status should also be treated as retryable.

    Returns
    -------
    bool
        Whether ``call_with_retry`` should retry this exception.
    """
    if not isinstance(exc, ynab.ApiException):
        return False
    if exc.status == 429:
        return True
    return include_5xx and exc.status is not None and 500 <= exc.status < 600


def call_with_retry(func: Callable[[], T], *, include_5xx: bool = True) -> T:
    """Call func(), retrying on transient YNAB API failures.

    Always retries on 429. Retries on 5xx too unless ``include_5xx=False``
    (set at call sites where a 5xx response is ambiguous about whether the
    write already landed -- retrying could duplicate it).

    Parameters
    ----------
    func : Callable[[], T]
        A zero-argument callable making one YNAB SDK call.
    include_5xx : bool, optional
        Whether a 5xx status is also retryable, by default ``True``.

    Returns
    -------
    T
        ``func()``'s return value, from whichever attempt succeeded.

    Raises
    ------
    ynab.ApiException
        Non-transient failures propagate on the first attempt. Once
        retries are exhausted, the original exception propagates
        unchanged (``reraise=True``).
    """
    retrying = tenacity.Retrying(
        stop=_stop,
        wait=_wait,
        retry=tenacity.retry_if_exception(
            lambda exc: _is_transient_ynab_error(exc, include_5xx=include_5xx)
        ),
        reraise=True,
    )
    return retrying(func)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_client.py -v`
Expected: All tests PASS (the 5 pre-existing tests plus the 6 new ones).

- [ ] **Step 6: Lint and type-check**

Run: `make lint`
Expected: No errors. If mypy complains about the `Callable`/`TypeVar` usage, confirm `from collections.abc import Callable` and `from typing import TypeVar` are both present and no other import is shadowing `Callable`.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/ynab_mcp/client.py tests/test_client.py
git commit -m "feat: add call_with_retry helper for transient YNAB API failures"
```

---

## Task 2: 429 error enrichment in `errors.py`

**Files:**
- Modify: `src/ynab_mcp/errors.py`
- Test: `tests/test_errors.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `translate_api_exception`'s signature and import path are unchanged; only its 429 output message changes.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_errors.py`:

```python
def test_translate_api_exception_enriches_429_with_rate_limit_guidance() -> None:
    """A 429 gets rate-limit context and retry-timing guidance appended."""
    exc = ynab.ApiException(
        status=429,
        reason="Too Many Requests",
        body='{"error": {"id": "429", "name": "too_many_requests", '
        '"detail": "Too many requests"}}',
    )

    result = translate_api_exception(exc)

    assert isinstance(result, ToolError)
    assert "Too many requests" in str(result)
    assert "rate limit" in str(result).lower()
    assert "hour" in str(result).lower()


def test_translate_api_exception_does_not_enrich_non_429() -> None:
    """A non-429 ApiException gets only the raw detail, no enrichment appended."""
    exc = ynab.ApiException(
        status=500,
        reason="Internal Server Error",
        body='{"error": {"id": "500", "name": "internal", '
        '"detail": "Service unavailable"}}',
    )

    result = translate_api_exception(exc)

    assert str(result) == "Service unavailable"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_errors.py -v`
Expected: `test_translate_api_exception_enriches_429_with_rate_limit_guidance` FAILS (no "rate limit"/"hour" text yet). `test_translate_api_exception_does_not_enrich_non_429` already PASSES (no enrichment exists yet at all) -- that's expected; it's a regression lock for after Step 4.

- [ ] **Step 3: Implement the enrichment**

In `src/ynab_mcp/errors.py`, replace the `translate_api_exception` function body:

```python
def translate_api_exception(exc: ynab.ApiException) -> ToolError:
    """Convert a YNAB ``ApiException`` into a FastMCP ``ToolError``.

    Parameters
    ----------
    exc : ynab.ApiException
        The exception raised by a ``ynab`` SDK API call.

    Returns
    -------
    fastmcp.exceptions.ToolError
        A ``ToolError`` carrying the YNAB API's error detail message, ready
        to be raised so the MCP client sees the real failure reason. A 429
        gets additional rate-limit context appended, since YNAB's raw
        detail for a 429 is just the four words "Too many requests" --
        not enough for the calling agent to explain what happened or judge
        whether/when to retry.
    """
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_errors.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/errors.py tests/test_errors.py
git commit -m "feat: enrich 429 errors with rate-limit context and retry guidance"
```

---

## Task 3: Wrap `accounts.py`

**Files:**
- Modify: `src/ynab_mcp/tools/accounts.py`
- Test: `tests/test_tools_accounts.py`

**Interfaces:**
- Consumes: `call_with_retry(func, *, include_5xx=True)` from `ynab_mcp.client`.

- [ ] **Step 1: Write the failing test**

Add `import tenacity` to the top of `tests/test_tools_accounts.py` (alongside the existing `import ynab`), then append:

```python
def test_list_accounts_retries_transient_failure(mocker: MockerFixture) -> None:
    """A transient 429 is retried and the eventual success is returned."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    client = mocker.Mock()
    accounts_api = mocker.patch("ynab_mcp.tools.accounts.ynab.AccountsApi")
    fake_accounts = [SimpleNamespace(id="a1", name="Checking")]
    accounts_api.return_value.get_accounts.side_effect = [
        ynab.ApiException(status=429, reason="Too Many Requests", body=None),
        SimpleNamespace(data=SimpleNamespace(accounts=fake_accounts)),
    ]

    result = list_accounts(client, "budget-1")

    assert result == fake_accounts
    assert accounts_api.return_value.get_accounts.call_count == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tools_accounts.py -v`
Expected: FAIL -- `list_accounts` raises a `ToolError` on the first (429) attempt instead of retrying.

- [ ] **Step 3: Implement the wrap**

In `src/ynab_mcp/tools/accounts.py`, change the import line and the call site:

```python
from ynab_mcp.client import call_with_retry, resolve_budget_id
```

```python
    api = ynab.AccountsApi(client)
    try:
        response = call_with_retry(lambda: api.get_accounts(plan_id=budget_id))
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return response.data.accounts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_accounts.py -v`
Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/tools/accounts.py tests/test_tools_accounts.py
git commit -m "feat: retry transient failures in list-accounts"
```

---

## Task 4: Wrap `budgets.py`

**Files:**
- Modify: `src/ynab_mcp/tools/budgets.py`
- Test: `tests/test_tools_budgets.py`

**Interfaces:**
- Consumes: `call_with_retry` from `ynab_mcp.client`.

- [ ] **Step 1: Write the failing test**

Add `import tenacity` to the top of `tests/test_tools_budgets.py`, then append:

```python
def test_list_budgets_retries_transient_failure(mocker: MockerFixture) -> None:
    """A transient 429 is retried and the eventual success is returned."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    client = mocker.Mock()
    plans_api = mocker.patch("ynab_mcp.tools.budgets.ynab.PlansApi")
    fake_plans = [SimpleNamespace(id="1", name="Family Budget")]
    plans_api.return_value.get_plans.side_effect = [
        ynab.ApiException(status=429, reason="Too Many Requests", body=None),
        SimpleNamespace(data=SimpleNamespace(plans=fake_plans)),
    ]

    result = list_budgets(client)

    assert result == fake_plans
    assert plans_api.return_value.get_plans.call_count == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tools_budgets.py -v`
Expected: FAIL -- `list_budgets` raises on the first attempt instead of retrying.

- [ ] **Step 3: Implement the wrap**

In `src/ynab_mcp/tools/budgets.py`, add the import and change the call site:

```python
from ynab_mcp.client import call_with_retry
from ynab_mcp.errors import translate_api_exception
```

```python
    api = ynab.PlansApi(client)
    try:
        response = call_with_retry(lambda: api.get_plans())
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return response.data.plans
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_budgets.py -v`
Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/tools/budgets.py tests/test_tools_budgets.py
git commit -m "feat: retry transient failures in list-budgets"
```

---

## Task 5: Wrap `categories.py`

**Files:**
- Modify: `src/ynab_mcp/tools/categories.py`
- Test: `tests/test_tools_categories.py`

**Interfaces:**
- Consumes: `call_with_retry` from `ynab_mcp.client`.

- [ ] **Step 1: Write the failing test**

Add `import tenacity` to the top of `tests/test_tools_categories.py`, then append:

```python
def test_list_categories_retries_transient_failure(mocker: MockerFixture) -> None:
    """A transient 429 is retried and the eventual success is returned."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    client = mocker.Mock()
    categories_api = mocker.patch("ynab_mcp.tools.categories.ynab.CategoriesApi")
    group_categories = [SimpleNamespace(id="c1", name="Groceries")]
    categories_api.return_value.get_categories.side_effect = [
        ynab.ApiException(status=429, reason="Too Many Requests", body=None),
        SimpleNamespace(
            data=SimpleNamespace(
                category_groups=[SimpleNamespace(categories=group_categories)]
            )
        ),
    ]

    result = list_categories(client, "budget-1")

    assert result == group_categories
    assert categories_api.return_value.get_categories.call_count == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tools_categories.py -v`
Expected: FAIL -- `list_categories` raises on the first attempt instead of retrying.

- [ ] **Step 3: Implement the wrap**

In `src/ynab_mcp/tools/categories.py`, add the import and change the call site:

```python
from ynab_mcp.client import call_with_retry, resolve_budget_id
```

```python
    api = ynab.CategoriesApi(client)
    try:
        response = call_with_retry(lambda: api.get_categories(plan_id=budget_id))
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
```

(the `return [category for group in ... ]` list-comprehension below stays unchanged)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_categories.py -v`
Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/tools/categories.py tests/test_tools_categories.py
git commit -m "feat: retry transient failures in list-categories"
```

---

## Task 6: Wrap `months.py`

**Files:**
- Modify: `src/ynab_mcp/tools/months.py`
- Test: `tests/test_tools_months.py`

**Interfaces:**
- Consumes: `call_with_retry` from `ynab_mcp.client`.

- [ ] **Step 1: Write the failing test**

Add `import tenacity` to the top of `tests/test_tools_months.py`, then append:

```python
def test_get_month_info_retries_transient_failure(mocker: MockerFixture) -> None:
    """A transient 429 is retried and the eventual success is returned."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    client = mocker.Mock()
    months_api = mocker.patch("ynab_mcp.tools.months.ynab.MonthsApi")
    fake_month = SimpleNamespace(month=date(2024, 3, 1), budgeted=100000)
    months_api.return_value.get_plan_month.side_effect = [
        ynab.ApiException(status=429, reason="Too Many Requests", body=None),
        SimpleNamespace(data=SimpleNamespace(month=fake_month)),
    ]

    result = get_month_info(client, "budget-1", "2024-03-01")

    assert result == fake_month
    assert months_api.return_value.get_plan_month.call_count == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tools_months.py -v`
Expected: FAIL -- `get_month_info` raises on the first attempt instead of retrying.

- [ ] **Step 3: Implement the wrap**

In `src/ynab_mcp/tools/months.py`, add the import and change the call site:

```python
from ynab_mcp.client import call_with_retry, resolve_budget_id
```

```python
    resolved_month = parse_month(month)
    api = ynab.MonthsApi(client)
    try:
        response = call_with_retry(
            lambda: api.get_plan_month(plan_id=budget_id, month=resolved_month)
        )
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return response.data.month
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_months.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/tools/months.py tests/test_tools_months.py
git commit -m "feat: retry transient failures in get-month-info"
```

---

## Task 7: Wrap `payees.py`

**Files:**
- Modify: `src/ynab_mcp/tools/payees.py`
- Test: `tests/test_tools_payees.py`

**Interfaces:**
- Consumes: `call_with_retry` from `ynab_mcp.client`.

- [ ] **Step 1: Write the failing test**

Add `import tenacity` to the top of `tests/test_tools_payees.py`, then append:

```python
def test_list_payees_retries_transient_failure(mocker: MockerFixture) -> None:
    """A transient 429 is retried and the eventual success is returned."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    client = mocker.Mock()
    payees_api = mocker.patch("ynab_mcp.tools.payees.ynab.PayeesApi")
    fake_payees = [SimpleNamespace(id="p1", name="Amazon")]
    payees_api.return_value.get_payees.side_effect = [
        ynab.ApiException(status=429, reason="Too Many Requests", body=None),
        SimpleNamespace(data=SimpleNamespace(payees=fake_payees)),
    ]

    result = list_payees(client, "budget-1")

    assert result == fake_payees
    assert payees_api.return_value.get_payees.call_count == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tools_payees.py -v`
Expected: FAIL -- `list_payees` raises on the first attempt instead of retrying.

- [ ] **Step 3: Implement the wrap**

In `src/ynab_mcp/tools/payees.py`, add the import and change the call site:

```python
from ynab_mcp.client import call_with_retry, resolve_budget_id
```

```python
    api = ynab.PayeesApi(client)
    try:
        response = call_with_retry(lambda: api.get_payees(plan_id=budget_id))
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return response.data.payees
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_payees.py -v`
Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/tools/payees.py tests/test_tools_payees.py
git commit -m "feat: retry transient failures in list-payees"
```

---

## Task 8: Wrap `transactions.py` (4 branches)

**Files:**
- Modify: `src/ynab_mcp/tools/transactions.py`
- Test: `tests/test_tools_transactions.py`

**Interfaces:**
- Consumes: `call_with_retry` from `ynab_mcp.client`.

- [ ] **Step 1: Write the failing test**

Add `import tenacity` to the top of `tests/test_tools_transactions.py`, then append:

```python
def test_list_transactions_retries_transient_failure(mocker: MockerFixture) -> None:
    """A transient 429 is retried and the eventual success is returned."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    client = mocker.Mock()
    transactions_api = mocker.patch("ynab_mcp.tools.transactions.ynab.TransactionsApi")
    fake_transactions = [SimpleNamespace(id="t1")]
    transactions_api.return_value.get_transactions.side_effect = [
        ynab.ApiException(status=429, reason="Too Many Requests", body=None),
        SimpleNamespace(data=SimpleNamespace(transactions=fake_transactions)),
    ]

    result = list_transactions(client, "budget-1")

    assert result == fake_transactions
    assert transactions_api.return_value.get_transactions.call_count == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tools_transactions.py -v`
Expected: FAIL -- `list_transactions` raises on the first attempt instead of retrying.

- [ ] **Step 3: Implement the wrap on all 4 branches**

In `src/ynab_mcp/tools/transactions.py`, add the import:

```python
from ynab_mcp.client import call_with_retry, resolve_budget_id
```

Replace the `try`/`except` block inside `list_transactions`:

```python
    api = ynab.TransactionsApi(client)
    try:
        if account_id is not None:
            response: Union[
                ynab.TransactionsResponse, ynab.HybridTransactionsResponse
            ] = call_with_retry(
                lambda: api.get_transactions_by_account(
                    plan_id=budget_id,
                    account_id=account_id,
                    since_date=since_date,
                    until_date=until_date,
                )
            )
        elif category_id is not None:
            response = call_with_retry(
                lambda: api.get_transactions_by_category(
                    plan_id=budget_id,
                    category_id=category_id,
                    since_date=since_date,
                    until_date=until_date,
                )
            )
        elif payee_id is not None:
            response = call_with_retry(
                lambda: api.get_transactions_by_payee(
                    plan_id=budget_id,
                    payee_id=payee_id,
                    since_date=since_date,
                    until_date=until_date,
                )
            )
        else:
            response = call_with_retry(
                lambda: api.get_transactions(
                    plan_id=budget_id, since_date=since_date, until_date=until_date
                )
            )
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return cast(list[ynab.TransactionDetail], response.data.transactions)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_transactions.py -v`
Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/tools/transactions.py tests/test_tools_transactions.py
git commit -m "feat: retry transient failures in list-transactions"
```

---

## Task 9: Wrap `lookup.py` (5 branches)

**Files:**
- Modify: `src/ynab_mcp/tools/lookup.py`
- Test: `tests/test_tools_lookup.py`

**Interfaces:**
- Consumes: `call_with_retry` from `ynab_mcp.client`.

- [ ] **Step 1: Write the failing test**

Add `import tenacity` to the top of `tests/test_tools_lookup.py`, then append (one representative test -- all 5 branches use the identical `call_with_retry` wrap, so this proves the pattern; the other 4 branches' existing tests already assert the exact call args unchanged):

```python
def test_lookup_account_retries_transient_failure(mocker: MockerFixture) -> None:
    """A transient 429 on the account branch is retried and succeeds."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    client = mocker.Mock()
    accounts_api = mocker.patch("ynab_mcp.tools.lookup.ynab.AccountsApi")
    fake_account = SimpleNamespace(id="a1", name="Checking")
    accounts_api.return_value.get_account_by_id.side_effect = [
        ynab.ApiException(status=429, reason="Too Many Requests", body=None),
        SimpleNamespace(data=SimpleNamespace(account=fake_account)),
    ]

    result = lookup_entity_by_id(client, "budget-1", "account", "a1")

    assert result == fake_account
    assert accounts_api.return_value.get_account_by_id.call_count == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tools_lookup.py -v`
Expected: FAIL -- the account branch raises on the first attempt instead of retrying.

- [ ] **Step 3: Implement the wrap on all 5 branches**

In `src/ynab_mcp/tools/lookup.py`, add the import:

```python
from ynab_mcp.client import call_with_retry, resolve_budget_id
```

Replace the `try`/`except` block inside `lookup_entity_by_id`:

```python
    try:
        if entity_type == "account":
            result: (
                ynab.Account
                | ynab.Category
                | ynab.Payee
                | ynab.TransactionDetail
                | ynab.MonthDetail
            ) = call_with_retry(
                lambda: ynab.AccountsApi(client).get_account_by_id(
                    plan_id=budget_id, account_id=entity_id
                )
            ).data.account
        elif entity_type == "category":
            result = call_with_retry(
                lambda: ynab.CategoriesApi(client).get_category_by_id(
                    plan_id=budget_id, category_id=entity_id
                )
            ).data.category
        elif entity_type == "payee":
            result = call_with_retry(
                lambda: ynab.PayeesApi(client).get_payee_by_id(
                    plan_id=budget_id, payee_id=entity_id
                )
            ).data.payee
        elif entity_type == "transaction":
            result = call_with_retry(
                lambda: ynab.TransactionsApi(client).get_transaction_by_id(
                    plan_id=budget_id, transaction_id=entity_id
                )
            ).data.transaction
        elif entity_type == "month":
            resolved_month = parse_month(entity_id)
            result = call_with_retry(
                lambda: ynab.MonthsApi(client).get_plan_month(
                    plan_id=budget_id, month=resolved_month
                )
            ).data.month
        else:
            raise ToolError(
                f"Unknown entity_type {entity_type!r}. Expected one of: "
                f"{_KNOWN_ENTITY_TYPES}."
            )
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return result
```

Note: `account_id=entity_id  # type: ignore[arg-type]` had a mypy ignore comment on the original chained-call line; if mypy flags the account branch after this change, re-add `# type: ignore[arg-type]` on the `account_id=entity_id` line.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_lookup.py -v`
Expected: All 8 tests PASS.

- [ ] **Step 5: Lint and type-check**

Run: `make lint`
Expected: No errors. Fix any mypy `arg-type` complaints per the note in Step 3.

- [ ] **Step 6: Commit**

```bash
git add src/ynab_mcp/tools/lookup.py tests/test_tools_lookup.py
git commit -m "feat: retry transient failures in lookup-entity-by-id"
```

---

## Task 10: Wrap `spend_analysis.py`

**Files:**
- Modify: `src/ynab_mcp/tools/spend_analysis.py`
- Test: `tests/test_tools_spend_analysis.py`

**Interfaces:**
- Consumes: `call_with_retry` from `ynab_mcp.client`.

Both `flag_category_spend` and `analyze_category_trends` call the shared `_fetch_month_categories` helper, so wrapping its one call site covers both public functions.

- [ ] **Step 1: Write the failing test**

Add `import tenacity` to the top of `tests/test_tools_spend_analysis.py`, then append:

```python
def test_fetch_month_categories_retries_transient_failure(
    mocker: MockerFixture,
) -> None:
    """A transient 429 is retried and the eventual success is returned."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    client = mocker.Mock()
    months_api = mocker.patch("ynab_mcp.tools.spend_analysis.ynab.MonthsApi")
    visible = SimpleNamespace(id="cat-1", hidden=False, deleted=False)
    months_api.return_value.get_plan_month.side_effect = [
        ynab.ApiException(status=429, reason="Too Many Requests", body=None),
        SimpleNamespace(data=SimpleNamespace(month=SimpleNamespace(categories=[visible]))),
    ]

    result = _fetch_month_categories(client, "budget-1", date(2024, 3, 1))

    assert result == [visible]
    assert months_api.return_value.get_plan_month.call_count == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tools_spend_analysis.py -v`
Expected: FAIL -- `_fetch_month_categories` raises on the first attempt instead of retrying.

- [ ] **Step 3: Implement the wrap**

In `src/ynab_mcp/tools/spend_analysis.py`, add the import:

```python
from ynab_mcp.client import call_with_retry, resolve_budget_id
```

Replace the `try`/`except` block inside `_fetch_month_categories`:

```python
    api = ynab.MonthsApi(client)
    try:
        response = call_with_retry(
            lambda: api.get_plan_month(plan_id=budget_id, month=month)
        )
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return [
        category
        for category in response.data.month.categories
        if not category.hidden and not category.deleted
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_spend_analysis.py -v`
Expected: All 24 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/tools/spend_analysis.py tests/test_tools_spend_analysis.py
git commit -m "feat: retry transient failures in flag-category-spend and analyze-category-trends"
```

---

## Task 11: N+1 fix + `since_date`/`until_date` in `payee_patterns.py`

**Files:**
- Modify: `src/ynab_mcp/tools/payee_patterns.py`
- Test: `tests/test_tools_payee_patterns.py`

**Interfaces:**
- Consumes: `list_transactions(client, budget_id, since_date=None, until_date=None)` from `ynab_mcp.tools.transactions` (already supports these kwargs -- no change needed there).
- Produces: `find_payee_transactions(client, budget_id, payee_query, fuzzy_threshold=0.6, since_date=None, until_date=None)`. `find-payee-transactions` MCP tool gains the same two optional parameters.
- No retry coverage change needed here -- `payee_patterns.py` gets it for free via `list_payees`/`list_transactions` (Tasks 7 and 8).

- [ ] **Step 1: Write the failing tests**

Add `from datetime import date` to the top of `tests/test_tools_payee_patterns.py`, then append:

```python
def test_find_payee_transactions_calls_list_transactions_once_for_multiple_matches(
    mocker: MockerFixture,
) -> None:
    """Multiple matched payees still call list_transactions exactly once."""
    client = mocker.Mock()
    list_payees_mock = mocker.patch("ynab_mcp.tools.payee_patterns.list_payees")
    list_payees_mock.return_value = [
        SimpleNamespace(id="p1", name="Amazon.com"),
        SimpleNamespace(id="p2", name="AMZN Mktp US Amazon"),
    ]
    list_transactions_mock = mocker.patch(
        "ynab_mcp.tools.payee_patterns.list_transactions"
    )
    list_transactions_mock.return_value = [
        _transaction(-5000, "Shopping"),
    ]

    find_payee_transactions(client, "budget-1", "amazon")

    list_transactions_mock.assert_called_once_with(
        client, "budget-1", since_date=None, until_date=None
    )


def test_find_payee_transactions_zero_matches_never_calls_list_transactions(
    mocker: MockerFixture,
) -> None:
    """No matched payees means list_transactions is never called at all."""
    client = mocker.Mock()
    list_payees_mock = mocker.patch("ynab_mcp.tools.payee_patterns.list_payees")
    list_payees_mock.return_value = [SimpleNamespace(id="p1", name="Netflix")]
    list_transactions_mock = mocker.patch(
        "ynab_mcp.tools.payee_patterns.list_transactions"
    )

    result = find_payee_transactions(client, "budget-1", "walmart")

    assert result == []
    list_transactions_mock.assert_not_called()


def test_find_payee_transactions_groups_batched_transactions_by_payee(
    mocker: MockerFixture,
) -> None:
    """The single batched call's transactions are grouped by payee_id client-side."""
    client = mocker.Mock()
    list_payees_mock = mocker.patch("ynab_mcp.tools.payee_patterns.list_payees")
    list_payees_mock.return_value = [
        SimpleNamespace(id="p1", name="Amazon.com"),
        SimpleNamespace(id="p2", name="AMZN Mktp US Amazon"),
    ]
    list_transactions_mock = mocker.patch(
        "ynab_mcp.tools.payee_patterns.list_transactions"
    )
    list_transactions_mock.return_value = [
        SimpleNamespace(payee_id="p1", amount=-5000, category_name="Shopping", subtransactions=[]),
        SimpleNamespace(payee_id="p2", amount=-3000, category_name="Shopping", subtransactions=[]),
        SimpleNamespace(payee_id="p2", amount=-3200, category_name="Shopping", subtransactions=[]),
        SimpleNamespace(payee_id=None, amount=-100, category_name=None, subtransactions=[]),
    ]

    result = find_payee_transactions(client, "budget-1", "amazon")

    assert len(result) == 2
    assert result[0].payee_id == "p1"
    assert result[0].transaction_count == 1
    assert result[1].payee_id == "p2"
    assert result[1].transaction_count == 2


def test_find_payee_transactions_forwards_since_date_and_until_date(
    mocker: MockerFixture,
) -> None:
    """since_date/until_date are forwarded to the single list_transactions call."""
    client = mocker.Mock()
    list_payees_mock = mocker.patch("ynab_mcp.tools.payee_patterns.list_payees")
    list_payees_mock.return_value = [SimpleNamespace(id="p1", name="Amazon.com")]
    list_transactions_mock = mocker.patch(
        "ynab_mcp.tools.payee_patterns.list_transactions"
    )
    list_transactions_mock.return_value = []

    find_payee_transactions(
        client,
        "budget-1",
        "amazon",
        since_date=date(2026, 1, 1),
        until_date=date(2026, 6, 30),
    )

    list_transactions_mock.assert_called_once_with(
        client, "budget-1", since_date=date(2026, 1, 1), until_date=date(2026, 6, 30)
    )
```

Note: the existing test `test_find_payee_transactions_returns_summary_for_matched_payee` asserts `list_transactions_mock.assert_called_once_with(client, "budget-1", payee_id="p1")` -- this assertion will now be WRONG (the call no longer passes `payee_id`) and must be updated in this same step to:

```python
    list_transactions_mock.assert_called_once_with(
        client, "budget-1", since_date=None, until_date=None
    )
```

Similarly, `test_find_payee_transactions_groups_are_not_pooled_across_payees`'s mock uses `side_effect = lambda client, budget_id, payee_id: transactions_by_payee[payee_id]` -- this must be replaced since `list_transactions` is now called once, unfiltered, returning ALL payees' transactions together. Replace that test's body with:

```python
def test_find_payee_transactions_groups_are_not_pooled_across_payees(
    mocker: MockerFixture,
) -> None:
    """Two matching payees produce two separate summaries, not one pooled group.

    "Amazon.com" and "AMZN Mktp US Amazon" both match a query of "amazon",
    but they're distinct payees with distinct transaction histories -- the
    spec's central requirement is that they stay split, not merged into a
    single combined summary.
    """
    client = mocker.Mock()
    list_payees_mock = mocker.patch("ynab_mcp.tools.payee_patterns.list_payees")
    list_payees_mock.return_value = [
        SimpleNamespace(id="p1", name="Amazon.com"),
        SimpleNamespace(id="p2", name="AMZN Mktp US Amazon"),
    ]
    list_transactions_mock = mocker.patch(
        "ynab_mcp.tools.payee_patterns.list_transactions"
    )
    list_transactions_mock.return_value = [
        SimpleNamespace(payee_id="p1", amount=-5000, category_name="Shopping", subtransactions=[]),
        SimpleNamespace(payee_id="p2", amount=-3000, category_name="Shopping", subtransactions=[]),
        SimpleNamespace(payee_id="p2", amount=-3200, category_name="Shopping", subtransactions=[]),
    ]

    result = find_payee_transactions(client, "budget-1", "amazon")

    assert len(result) == 2
    assert result[0].payee_id == "p1"
    assert result[0].transaction_count == 1
    assert result[1].payee_id == "p2"
    assert result[1].transaction_count == 2
```

And `test_find_payee_transactions_excludes_payee_with_no_transactions` -- its `list_transactions_mock.return_value = []` still works unchanged (an empty batch means every matched payee has zero transactions), no edit needed there.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_payee_patterns.py -v`
Expected: The 4 new tests FAIL (`find_payee_transactions` doesn't accept `since_date`/`until_date` yet, and still calls `list_transactions` per-payee with `payee_id=`). The edited existing tests also FAIL against the still-unbatched implementation.

- [ ] **Step 3: Implement the N+1 fix and new parameters**

In `src/ynab_mcp/tools/payee_patterns.py`, add `from collections import defaultdict` to the existing `from collections import Counter` import (change to `from collections import Counter, defaultdict`), add `from datetime import date` near the top, and replace `find_payee_transactions`:

```python
def find_payee_transactions(
    client: ynab.ApiClient,
    budget_id: str,
    payee_query: str,
    fuzzy_threshold: float = 0.6,
    since_date: date | None = None,
    until_date: date | None = None,
) -> list[PayeeGroupSummary]:
    """Find transaction patterns for payees matching a query.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id (translated to the SDK's ``plan_id``).
    payee_query : str
        A payee name or substring to search for.
    fuzzy_threshold : float, optional
        The minimum ``difflib`` similarity ratio for a non-substring
        match, by default ``0.6``.
    since_date : datetime.date | None, optional
        Only consider transactions on or after this date, by default
        ``None`` (YNAB's own API defaults to one year ago).
    until_date : datetime.date | None, optional
        Only consider transactions on or before this date, by default
        ``None``.

    Returns
    -------
    list[PayeeGroupSummary]
        One summary per matched payee with at least one transaction.
        Empty if no payee matches ``payee_query``.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If ``payee_query`` is empty or whitespace-only, or if an
        underlying YNAB API request fails.
    """
    if not payee_query.strip():
        raise ToolError("payee_query must not be empty.")

    payees = list_payees(client, budget_id)
    matches = _match_payees(payees, payee_query, fuzzy_threshold)
    if not matches:
        return []

    all_transactions = list_transactions(
        client, budget_id, since_date=since_date, until_date=until_date
    )
    transactions_by_payee_id: dict[str, list[ynab.TransactionDetail]] = defaultdict(
        list
    )
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

Update `register`'s inner tool function to accept and forward the same two parameters:

```python
    @mcp.tool(name="find-payee-transactions")
    def find_payee_transactions_tool(
        payee_query: str,
        budget_id: str | None = None,
        since_date: date | None = None,
        until_date: date | None = None,
    ) -> list[dict[str, object]]:
        """Find transaction patterns for payees matching a query.

        Parameters
        ----------
        payee_query : str
            A payee name or substring to search for.
        budget_id : str | None, optional
            The YNAB budget id, by default ``None`` (falls back to
            ``YNAB_DEFAULT_BUDGET_ID``).
        since_date : datetime.date | None, optional
            Only consider transactions on or after this date, by default
            ``None`` (YNAB's own API defaults to one year ago).
        until_date : datetime.date | None, optional
            Only consider transactions on or before this date, by default
            ``None``.
        """
        resolved_budget_id = resolve_budget_id(budget_id, settings)
        summaries = find_payee_transactions(
            client,
            resolved_budget_id,
            payee_query,
            since_date=since_date,
            until_date=until_date,
        )
        return [asdict(summary) for summary in summaries]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_payee_patterns.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Lint and type-check**

Run: `make lint`

- [ ] **Step 6: Commit**

```bash
git add src/ynab_mcp/tools/payee_patterns.py tests/test_tools_payee_patterns.py
git commit -m "fix: batch find-payee-transactions into one list_transactions call"
```

---

## Task 12: Wrap `budgeted_amount.py` (6 call sites)

**Files:**
- Modify: `src/ynab_mcp/tools/budgeted_amount.py`
- Test: `tests/test_tools_budgeted_amount.py`

**Interfaces:**
- Consumes: `call_with_retry` from `ynab_mcp.client` (`include_5xx=True`, the default, everywhere in this file -- every write here sets an absolute value computed from a prior read, so it's idempotent to resend).

There are 6 call sites: `assign_budgeted_amount`'s one `update_month_category` call, and `move_budgeted_amount`'s two `get_month_category_by_id` reads plus its decrement `update_month_category`, increment `update_month_category`, and rollback `update_month_category`. Two wiring tests cover the pattern (one per function) rather than one per call site, since all 6 share the identical `include_5xx=True` configuration -- code review confirms each site was wrapped consistently.

- [ ] **Step 1: Write the failing tests**

Add `import tenacity` to the top of `tests/test_tools_budgeted_amount.py`, then append:

```python
def test_assign_budgeted_amount_retries_transient_failure(
    mocker: MockerFixture,
) -> None:
    """A transient 429 is retried and the eventual success is returned."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    client = mocker.Mock()
    categories_api = mocker.patch("ynab_mcp.tools.budgeted_amount.ynab.CategoriesApi")
    fake_category = SimpleNamespace(id="cat-1", budgeted=50000)
    categories_api.return_value.update_month_category.side_effect = [
        ynab.ApiException(status=429, reason="Too Many Requests", body=None),
        SimpleNamespace(data=SimpleNamespace(category=fake_category)),
    ]

    result = assign_budgeted_amount(client, "budget-1", "current", "cat-1", 50000)

    assert result == fake_category
    assert categories_api.return_value.update_month_category.call_count == 2


def test_move_budgeted_amount_retries_transient_failure_on_first_read(
    mocker: MockerFixture,
) -> None:
    """A transient 429 on the first read is retried; the whole move still succeeds."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    client = mocker.Mock()
    categories_api = mocker.patch("ynab_mcp.tools.budgeted_amount.ynab.CategoriesApi")
    categories_api.return_value.get_month_category_by_id.side_effect = [
        ynab.ApiException(status=429, reason="Too Many Requests", body=None),
        SimpleNamespace(
            data=SimpleNamespace(category=SimpleNamespace(budgeted=100000))
        ),
        SimpleNamespace(data=SimpleNamespace(category=SimpleNamespace(budgeted=20000))),
    ]
    updated_from = SimpleNamespace(id="from-cat", budgeted=80000)
    updated_to = SimpleNamespace(id="to-cat", budgeted=40000)
    categories_api.return_value.update_month_category.side_effect = [
        SimpleNamespace(data=SimpleNamespace(category=updated_from)),
        SimpleNamespace(data=SimpleNamespace(category=updated_to)),
    ]

    result = move_budgeted_amount(
        client, "budget-1", "current", "from-cat", "to-cat", 20000
    )

    assert result == {"from_category": updated_from, "to_category": updated_to}
    assert categories_api.return_value.get_month_category_by_id.call_count == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_budgeted_amount.py -v`
Expected: Both new tests FAIL -- the 429 propagates as a `ToolError` on the first attempt instead of retrying.

- [ ] **Step 3: Implement the wraps**

In `src/ynab_mcp/tools/budgeted_amount.py`, add the import:

```python
from ynab_mcp.client import call_with_retry, require_writable, resolve_budget_id
```

Replace `assign_budgeted_amount`'s body:

```python
    resolved_month = parse_month(month)
    api = ynab.CategoriesApi(client)
    try:
        response = call_with_retry(
            lambda: api.update_month_category(
                plan_id=budget_id,
                month=resolved_month,
                category_id=category_id,
                data=ynab.PatchMonthCategoryWrapper(
                    category=ynab.SaveMonthCategory(budgeted=amount)
                ),
            )
        )
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return response.data.category
```

Replace `move_budgeted_amount`'s body (from `resolved_month = parse_month(month)` through the final `return`):

```python
    resolved_month = parse_month(month)
    api = ynab.CategoriesApi(client)
    try:
        from_current = call_with_retry(
            lambda: api.get_month_category_by_id(
                plan_id=budget_id, month=resolved_month, category_id=from_category_id
            )
        ).data.category.budgeted
        to_current = call_with_retry(
            lambda: api.get_month_category_by_id(
                plan_id=budget_id, month=resolved_month, category_id=to_category_id
            )
        ).data.category.budgeted
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc

    try:
        from_category = call_with_retry(
            lambda: api.update_month_category(
                plan_id=budget_id,
                month=resolved_month,
                category_id=from_category_id,
                data=ynab.PatchMonthCategoryWrapper(
                    category=ynab.SaveMonthCategory(budgeted=from_current - amount)
                ),
            )
        ).data.category
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc

    try:
        to_category = call_with_retry(
            lambda: api.update_month_category(
                plan_id=budget_id,
                month=resolved_month,
                category_id=to_category_id,
                data=ynab.PatchMonthCategoryWrapper(
                    category=ynab.SaveMonthCategory(budgeted=to_current + amount)
                ),
            )
        ).data.category
    except ynab.ApiException as exc:
        target_detail = str(translate_api_exception(exc))
        try:
            call_with_retry(
                lambda: api.update_month_category(
                    plan_id=budget_id,
                    month=resolved_month,
                    category_id=from_category_id,
                    data=ynab.PatchMonthCategoryWrapper(
                        category=ynab.SaveMonthCategory(budgeted=from_current)
                    ),
                )
            )
        except ynab.ApiException as rollback_exc:
            rollback_detail = str(translate_api_exception(rollback_exc))
            raise ToolError(
                f"Failed to move {amount} from {from_category_id} to "
                f"{to_category_id} for {month}: {target_detail}. Rollback of "
                f"the source category also failed ({rollback_detail}) -- "
                f"{from_category_id} is left decremented by {amount} for "
                f"{month} and needs manual correction."
            ) from rollback_exc
        raise ToolError(
            f"Failed to move {amount} from {from_category_id} to "
            f"{to_category_id} for {month}: {target_detail}. The source "
            "category was restored to its original budgeted amount."
        ) from exc

    return {"from_category": from_category, "to_category": to_category}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_budgeted_amount.py -v`
Expected: All 11 tests PASS (9 pre-existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/tools/budgeted_amount.py tests/test_tools_budgeted_amount.py
git commit -m "feat: retry transient failures in manage-budgeted-amount"
```

---

## Task 13: Wrap `payees_write.py` (3 call sites)

**Files:**
- Modify: `src/ynab_mcp/tools/payees_write.py`
- Test: `tests/test_tools_payees_write.py`

**Interfaces:**
- Consumes: `call_with_retry` from `ynab_mcp.client` (`include_5xx=True`, the default -- both writes here set an absolute `name`, idempotent to resend).

- [ ] **Step 1: Write the failing tests**

Add `import tenacity` to the top of `tests/test_tools_payees_write.py`, then append:

```python
def test_rename_payee_retries_transient_failure(mocker: MockerFixture) -> None:
    """A transient 429 is retried and the eventual success is returned."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    client = mocker.Mock()
    payees_api = mocker.patch("ynab_mcp.tools.payees_write.ynab.PayeesApi")
    fake_payee = SimpleNamespace(id="p1", name="Amazon")
    payees_api.return_value.update_payee.side_effect = [
        ynab.ApiException(status=429, reason="Too Many Requests", body=None),
        SimpleNamespace(data=SimpleNamespace(payee=fake_payee)),
    ]

    result = rename_payee(client, "budget-1", "p1", "Amazon")

    assert result == fake_payee
    assert payees_api.return_value.update_payee.call_count == 2


def test_merge_payees_retries_transient_failure_on_read(
    mocker: MockerFixture,
) -> None:
    """A transient 429 on the target read is retried; the merge still succeeds."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    client = mocker.Mock()
    payees_api = mocker.patch("ynab_mcp.tools.payees_write.ynab.PayeesApi")
    target_payee = SimpleNamespace(id="p2", name="Amazon.com")
    merged_payee = SimpleNamespace(id="p1", name="Amazon.com")
    payees_api.return_value.get_payee_by_id.side_effect = [
        ynab.ApiException(status=429, reason="Too Many Requests", body=None),
        SimpleNamespace(data=SimpleNamespace(payee=target_payee)),
    ]
    payees_api.return_value.update_payee.return_value = SimpleNamespace(
        data=SimpleNamespace(payee=merged_payee)
    )

    result = merge_payees(client, "budget-1", "p1", "p2")

    assert result == merged_payee
    assert payees_api.return_value.get_payee_by_id.call_count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_payees_write.py -v`
Expected: Both new tests FAIL -- the 429 propagates on the first attempt instead of retrying.

- [ ] **Step 3: Implement the wraps**

In `src/ynab_mcp/tools/payees_write.py`, add the import:

```python
from ynab_mcp.client import call_with_retry, require_writable, resolve_budget_id
```

Replace `rename_payee`'s body:

```python
    api = ynab.PayeesApi(client)
    try:
        response = call_with_retry(
            lambda: api.update_payee(
                plan_id=budget_id,
                payee_id=payee_id,
                data=ynab.PatchPayeeWrapper(payee=ynab.SavePayee(name=new_name)),
            )
        )
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return response.data.payee
```

Replace `merge_payees`'s body:

```python
    api = ynab.PayeesApi(client)
    try:
        target = call_with_retry(
            lambda: api.get_payee_by_id(plan_id=budget_id, payee_id=target_payee_id)
        )
        response = call_with_retry(
            lambda: api.update_payee(
                plan_id=budget_id,
                payee_id=source_payee_id,
                data=ynab.PatchPayeeWrapper(
                    payee=ynab.SavePayee(name=target.data.payee.name)
                ),
            )
        )
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return response.data.payee
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_payees_write.py -v`
Expected: All 10 tests PASS (8 pre-existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/tools/payees_write.py tests/test_tools_payees_write.py
git commit -m "feat: retry transient failures in manage-payees"
```

---

## Task 14: Wrap `scheduled_transactions.py` (3 call sites, create is 429-only)

**Files:**
- Modify: `src/ynab_mcp/tools/scheduled_transactions.py`
- Test: `tests/test_tools_scheduled_transactions.py`

**Interfaces:**
- Consumes: `call_with_retry` from `ynab_mcp.client`. `create_scheduled_transaction`'s call site passes `include_5xx=False` (no dedup key on this create -- see spec's "Idempotency and write-path retry safety"). `update_scheduled_transaction` (full-replace PUT by id) and `delete_scheduled_transaction` use the default `include_5xx=True`.

- [ ] **Step 1: Write the failing tests**

Add `import tenacity` to the top of `tests/test_tools_scheduled_transactions.py`, then append:

```python
def test_create_scheduled_transaction_retries_transient_429(
    mocker: MockerFixture,
) -> None:
    """A transient 429 is retried even though this create is 429-only."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    client = mocker.Mock()
    api = mocker.patch(
        "ynab_mcp.tools.scheduled_transactions.ynab.ScheduledTransactionsApi"
    )
    fake_scheduled = SimpleNamespace(id="st1")
    api.return_value.create_scheduled_transaction.side_effect = [
        ynab.ApiException(status=429, reason="Too Many Requests", body=None),
        SimpleNamespace(data=SimpleNamespace(scheduled_transaction=fake_scheduled)),
    ]

    result = create_scheduled_transaction(
        client,
        "budget-1",
        "11111111-1111-1111-1111-111111111111",
        date(2024, 3, 1),
        -50000,
        "monthly",
    )

    assert result == fake_scheduled
    assert api.return_value.create_scheduled_transaction.call_count == 2


def test_create_scheduled_transaction_does_not_retry_5xx(
    mocker: MockerFixture,
) -> None:
    """A 5xx on create is ambiguous (may have already landed) -- no retry."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    client = mocker.Mock()
    api = mocker.patch(
        "ynab_mcp.tools.scheduled_transactions.ynab.ScheduledTransactionsApi"
    )
    exc = ynab.ApiException(
        status=500,
        reason="Internal Server Error",
        body='{"error": {"id": "500", "name": "internal", '
        '"detail": "Service unavailable"}}',
    )
    api.return_value.create_scheduled_transaction.side_effect = [
        exc,
        SimpleNamespace(data=SimpleNamespace(scheduled_transaction=SimpleNamespace())),
    ]

    with raises(ToolError, match="Service unavailable"):
        create_scheduled_transaction(
            client,
            "budget-1",
            "11111111-1111-1111-1111-111111111111",
            date(2024, 3, 1),
            -50000,
            "monthly",
        )

    assert api.return_value.create_scheduled_transaction.call_count == 1


def test_update_scheduled_transaction_retries_transient_failure(
    mocker: MockerFixture,
) -> None:
    """A transient 429 is retried and the eventual success is returned."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    client = mocker.Mock()
    api = mocker.patch(
        "ynab_mcp.tools.scheduled_transactions.ynab.ScheduledTransactionsApi"
    )
    fake_scheduled = SimpleNamespace(id="st1")
    api.return_value.update_scheduled_transaction.side_effect = [
        ynab.ApiException(status=429, reason="Too Many Requests", body=None),
        SimpleNamespace(data=SimpleNamespace(scheduled_transaction=fake_scheduled)),
    ]

    result = update_scheduled_transaction(
        client,
        "budget-1",
        "st1",
        "11111111-1111-1111-1111-111111111111",
        date(2024, 3, 1),
        -60000,
        "monthly",
    )

    assert result == fake_scheduled
    assert api.return_value.update_scheduled_transaction.call_count == 2


def test_delete_scheduled_transaction_retries_transient_failure(
    mocker: MockerFixture,
) -> None:
    """A transient 429 is retried and the eventual success is returned."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    client = mocker.Mock()
    api = mocker.patch(
        "ynab_mcp.tools.scheduled_transactions.ynab.ScheduledTransactionsApi"
    )
    fake_scheduled = SimpleNamespace(id="st1", deleted=True)
    api.return_value.delete_scheduled_transaction.side_effect = [
        ynab.ApiException(status=429, reason="Too Many Requests", body=None),
        SimpleNamespace(data=SimpleNamespace(scheduled_transaction=fake_scheduled)),
    ]

    result = delete_scheduled_transaction(client, "budget-1", "st1")

    assert result == fake_scheduled
    assert api.return_value.delete_scheduled_transaction.call_count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_scheduled_transactions.py -v`
Expected: All 4 new tests FAIL -- none of the call sites retry yet.

- [ ] **Step 3: Implement the wraps**

In `src/ynab_mcp/tools/scheduled_transactions.py`, add the import:

```python
from ynab_mcp.client import call_with_retry, require_writable, resolve_budget_id
```

Replace `create_scheduled_transaction`'s body:

```python
    api = ynab.ScheduledTransactionsApi(client)
    try:
        response = call_with_retry(
            lambda: api.create_scheduled_transaction(
                plan_id=budget_id,
                data=ynab.PostScheduledTransactionWrapper(
                    scheduled_transaction=ynab.SaveScheduledTransaction(
                        account_id=account_id,
                        var_date=date,
                        amount=amount,
                        payee_id=payee_id,
                        payee_name=payee_name,
                        category_id=category_id,
                        memo=memo,
                        flag_color=flag_color,
                        frequency=frequency,
                    )
                ),
            ),
            include_5xx=False,
        )
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return response.data.scheduled_transaction
```

Replace `update_scheduled_transaction`'s body:

```python
    api = ynab.ScheduledTransactionsApi(client)
    try:
        response = call_with_retry(
            lambda: api.update_scheduled_transaction(
                plan_id=budget_id,
                scheduled_transaction_id=scheduled_transaction_id,
                put_scheduled_transaction_wrapper=ynab.PutScheduledTransactionWrapper(
                    scheduled_transaction=ynab.SaveScheduledTransaction(
                        account_id=account_id,
                        var_date=date,
                        amount=amount,
                        payee_id=payee_id,
                        payee_name=payee_name,
                        category_id=category_id,
                        memo=memo,
                        flag_color=flag_color,
                        frequency=frequency,
                    )
                ),
            )
        )
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return response.data.scheduled_transaction
```

Replace `delete_scheduled_transaction`'s body:

```python
    api = ynab.ScheduledTransactionsApi(client)
    try:
        response = call_with_retry(
            lambda: api.delete_scheduled_transaction(
                plan_id=budget_id, scheduled_transaction_id=scheduled_transaction_id
            )
        )
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return response.data.scheduled_transaction
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_scheduled_transactions.py -v`
Expected: All 17 tests PASS (13 pre-existing + 4 new).

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/tools/scheduled_transactions.py tests/test_tools_scheduled_transactions.py
git commit -m "feat: retry transient failures in manage-scheduled-transaction"
```

---

## Task 15: Wrap `transactions_write.py` (3 call sites, create group is 429-only)

**Files:**
- Modify: `src/ynab_mcp/tools/transactions_write.py`
- Test: `tests/test_tools_transactions_write.py`

**Interfaces:**
- Consumes: `call_with_retry` from `ynab_mcp.client`. The grouped `create_transaction` call passes `include_5xx=False` (no dedup key on these creates). The grouped `update_transactions_with_http_info` call (PATCH by id, absolute field values) and the per-item `delete_transaction` loop use the default `include_5xx=True`.

- [ ] **Step 1: Write the failing tests**

Add `import tenacity` and `import ynab` to the top of `tests/test_tools_transactions_write.py` (check `ynab` isn't already imported -- it is, per the existing file; only add `import tenacity`), then append:

```python
def test_bulk_manage_transactions_create_retries_transient_429(
    mocker: MockerFixture,
) -> None:
    """A transient 429 on the create group is retried and succeeds."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    client = mocker.Mock()
    transactions_api = mocker.patch(
        "ynab_mcp.tools.transactions_write.ynab.TransactionsApi"
    )
    transactions_api.return_value.create_transaction.side_effect = [
        ynab.ApiException(status=429, reason="Too Many Requests", body=None),
        SimpleNamespace(data=SimpleNamespace(transactions=[SimpleNamespace(id="new-1")])),
    ]

    operations: list[dict[str, object]] = [
        {
            "action": "create",
            "account_id": "11111111-1111-1111-1111-111111111111",
            "amount": -1000,
        },
    ]

    result = bulk_manage_transactions(client, "budget-1", operations)

    assert result == [{"action": "create", "id": "new-1", "status": "ok", "detail": None}]
    assert transactions_api.return_value.create_transaction.call_count == 2


def test_bulk_manage_transactions_create_does_not_retry_5xx(
    mocker: MockerFixture,
) -> None:
    """A 5xx on create is ambiguous (may have already landed) -- no retry."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    client = mocker.Mock()
    transactions_api = mocker.patch(
        "ynab_mcp.tools.transactions_write.ynab.TransactionsApi"
    )
    transactions_api.return_value.create_transaction.side_effect = [
        ynab.ApiException(
            status=500,
            reason="Internal Server Error",
            body='{"error": {"id": "500", "name": "internal", '
            '"detail": "Service unavailable"}}',
        ),
        SimpleNamespace(data=SimpleNamespace(transactions=[SimpleNamespace(id="new-1")])),
    ]

    operations: list[dict[str, object]] = [
        {
            "action": "create",
            "account_id": "11111111-1111-1111-1111-111111111111",
            "amount": -1000,
        },
    ]

    result = bulk_manage_transactions(client, "budget-1", operations)

    assert result[0]["status"] == "error"
    assert result[0]["detail"] == "Service unavailable"
    assert transactions_api.return_value.create_transaction.call_count == 1


def test_bulk_manage_transactions_update_retries_transient_429(
    mocker: MockerFixture,
) -> None:
    """A transient 429 on the update group is retried and succeeds."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    client = mocker.Mock()
    transactions_api = mocker.patch(
        "ynab_mcp.tools.transactions_write.ynab.TransactionsApi"
    )
    updated_raw = json.dumps(
        {
            "data": {
                "transaction_ids": ["txn-1"],
                "transactions": [
                    {
                        "id": "txn-1",
                        "date": "2026-07-14",
                        "amount": -5000,
                        "cleared": "uncleared",
                        "approved": True,
                        "deleted": False,
                        "account_id": "11111111-1111-1111-1111-111111111111",
                        "account_name": "test account",
                        "subtransactions": [],
                    }
                ],
                "duplicate_import_ids": [],
                "server_knowledge": 1,
            }
        }
    ).encode()
    transactions_api.return_value.update_transactions_with_http_info.side_effect = [
        ynab.ApiException(status=429, reason="Too Many Requests", body=None),
        SimpleNamespace(raw_data=updated_raw),
    ]

    operations: list[dict[str, object]] = [
        {"action": "update", "id": "txn-1", "approved": True},
    ]

    result = bulk_manage_transactions(client, "budget-1", operations)

    assert result == [{"action": "update", "id": "txn-1", "status": "ok", "detail": None}]
    assert (
        transactions_api.return_value.update_transactions_with_http_info.call_count == 2
    )


def test_bulk_manage_transactions_delete_retries_transient_429(
    mocker: MockerFixture,
) -> None:
    """A transient 429 on a delete is retried and succeeds."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    client = mocker.Mock()
    transactions_api = mocker.patch(
        "ynab_mcp.tools.transactions_write.ynab.TransactionsApi"
    )
    transactions_api.return_value.delete_transaction.side_effect = [
        ynab.ApiException(status=429, reason="Too Many Requests", body=None),
        SimpleNamespace(data=SimpleNamespace(transaction=SimpleNamespace(id="txn-2"))),
    ]

    operations: list[dict[str, object]] = [{"action": "delete", "id": "txn-2"}]

    result = bulk_manage_transactions(client, "budget-1", operations)

    assert result == [{"action": "delete", "id": "txn-2", "status": "ok", "detail": None}]
    assert transactions_api.return_value.delete_transaction.call_count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_transactions_write.py -v`
Expected: All 4 new tests FAIL -- none of the call sites retry yet (the 5xx-no-retry test also fails since the first `side_effect` exception is raised and reported as an error, matching intended behavior only after the create group is wrapped with `include_5xx=False`; verify it fails at the assertion checking `call_count == 1` is trivially true today but the retry tests fail on `call_count == 2` and `result == [...]`).

- [ ] **Step 3: Implement the wraps**

In `src/ynab_mcp/tools/transactions_write.py`, add the import:

```python
from ynab_mcp.client import call_with_retry, require_writable, resolve_budget_id
```

Replace the create-group `try` block inside `bulk_manage_transactions`:

```python
    if create_indices:
        try:
            response = call_with_retry(
                lambda: api.create_transaction(
                    plan_id=budget_id,
                    data=ynab.PostTransactionsWrapper(
                        transactions=[
                            _build_new_transaction(operations[i])
                            for i in create_indices
                        ]
                    ),
                ),
                include_5xx=False,
            )
            created = response.data.transactions or []
```

(the rest of the create-group block -- the `for i, transaction in zip(...)` loop and the two `except` clauses -- stays unchanged)

Replace the update-group `try` block:

```python
    if update_indices:
        try:
            # The installed ynab SDK (v4.2.0) maps this endpoint's success
            # response to HTTP status '209' instead of the '200' YNAB
            # actually returns, so update_transactions()'s built-in
            # deserialization silently yields None on a real success.
            # Parsing raw_data directly with the response model sidesteps
            # that broken status-code map.
            http_response = call_with_retry(
                lambda: api.update_transactions_with_http_info(
                    plan_id=budget_id,
                    data=ynab.PatchTransactionsWrapper(
                        transactions=[
                            _build_updated_transaction(operations[i])
                            for i in update_indices
                        ]
                    ),
                )
            )
            response = ynab.SaveTransactionsResponse.model_validate_json(
                http_response.raw_data
            )
            updated = response.data.transactions or []
```

(the rest of the update-group block stays unchanged)

Replace the delete loop:

```python
    delete_indices = [i for i, op in enumerate(operations) if op["action"] == "delete"]
    for i in delete_indices:
        transaction_id = str(operations[i]["id"])
        try:
            call_with_retry(
                lambda: api.delete_transaction(
                    plan_id=budget_id, transaction_id=transaction_id
                )
            )
            results[i] = {
                "action": "delete",
                "id": transaction_id,
                "status": "ok",
                "detail": None,
            }
        except ynab.ApiException as exc:
            results[i] = {
                "action": "delete",
                "id": transaction_id,
                "status": "error",
                "detail": str(translate_api_exception(exc)),
            }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_transactions_write.py -v`
Expected: All 11 tests PASS (7 pre-existing + 4 new).

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/tools/transactions_write.py tests/test_tools_transactions_write.py
git commit -m "feat: retry transient failures in bulk-manage-transactions"
```

---

## Task 16: Full-suite verification

**Files:** none (verification only)

**Interfaces:** none.

- [ ] **Step 1: Run the full test suite**

Run: `make tests`
Expected: All tests pass, no regressions across the 12 direct-edit modules, the 2 delegation modules (`payee_patterns.py`, `find_amazon_transactions.py`), and `errors.py`.

- [ ] **Step 2: Run lint and type-check**

Run: `make lint`
Expected: No errors.

- [ ] **Step 3: Run the coverage gate**

Run: `make coverage`
Expected: Passes the 80% threshold.

- [ ] **Step 4: Confirm no leftover TODOs or debug code**

Run: `git diff main --stat` (from the branch) to review the full set of changed files against the "Module coverage" list in the design spec -- confirm all 12 direct-edit modules plus `client.py` and `errors.py` appear, and `payee_patterns.py` and `find_amazon_transactions.py` (delegation-only) do NOT need direct changes beyond `payee_patterns.py`'s N+1 fix (already committed in Task 11).

This task has no code changes and no commit -- it's the final gate before build-from-issue's own Step 6 (project E2E) and Step 7 (acceptance-criteria audit) run.
