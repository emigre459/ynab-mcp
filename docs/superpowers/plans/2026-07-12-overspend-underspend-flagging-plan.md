# Overspend/Underspend Flagging & Trend Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two read-only MCP tools — `flag-category-spend` (single-month over/under-spend flagging) and `analyze-category-trends` (multi-month pattern detection) — to the ynab-mcp server.

**Architecture:** One new module, `src/ynab_mcp/tools/spend_analysis.py`, houses both tools plus shared pure helpers (milliunit-to-dollar conversion, per-category-month over/under classification, trailing-month-window computation). Each tool has a plain testable function (returning `list[dict[str, object]]` directly, since the output is a derived analysis, not a single SDK model dump) plus a thin `@mcp.tool` wrapper, matching the pattern in `tools/months.py` and `tools/transactions.py`. Both wrap `ynab.MonthsApi.get_plan_month`, reuse `parse_month` from `tools/months.py`, `resolve_budget_id` from `client.py`, and `translate_api_exception` from `errors.py`.

**Tech Stack:** Python 3.13, FastMCP v3, official `ynab` PyPI client, pytest + pytest-mock, uv.

## Global Constraints

- Read-only: no write/budget-adjustment calls anywhere in this module (spec: Why / Out of scope).
- YNAB milliunit fields are converted to dollars (float, rounded to 2 decimals) in all tool output (spec: Shared concepts — Spend normalization).
- Hidden (`hidden=True`) and deleted (`deleted=True`) categories are excluded from both tools' output entirely (spec: Shared concepts).
- `flag-category-spend` default `threshold=0.10`; `analyze-category-trends` defaults `months=6`, `end_month="current"`, `overspend_threshold=0.10`, `majority_ratio=0.5` (spec: Tool 1 / Tool 2 parameters).
- Zero-budgeted category with nonzero spend → always flagged as overspend; zero-budgeted with zero spend → never flagged (spec: Shared concepts — Percent-over/under calculation).
- Every `ynab.ApiException` is translated via `translate_api_exception` before raising (spec: Error handling). Invalid params (`threshold`/`overspend_threshold < 0`, `majority_ratio` outside `(0, 1]`, `months < 1`) raise `ToolError` before any API call.
- Follow existing numpydoc-style docstrings (see `src/ynab_mcp/tools/months.py`) for every public and module-level function.

---

### Task 1: Pure helper functions (dollar conversion, classification, trailing-month window)

**Files:**
- Create: `src/ynab_mcp/tools/spend_analysis.py`
- Test: `tests/test_tools_spend_analysis.py`

**Interfaces:**
- Consumes: nothing (pure functions, no I/O).
- Produces:
  - `_to_dollars(milliunits: int) -> float`
  - `_spent_milli(category: ynab.Category) -> int`
  - `_percent_diff(budgeted: int, spent: int) -> float | None`
  - `_direction(budgeted: int, spent: int, threshold: float) -> str | None`
  - `_trailing_months(end_month: date, months: int) -> list[date]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tools_spend_analysis.py` with:

```python
"""Tests for ynab_mcp.tools.spend_analysis."""

from datetime import date
from types import SimpleNamespace

from ynab_mcp.tools.spend_analysis import (
    _direction,
    _percent_diff,
    _spent_milli,
    _to_dollars,
    _trailing_months,
)


def test_to_dollars_converts_milliunits() -> None:
    """Milliunits convert to dollars, rounded to 2 decimals."""
    assert _to_dollars(420000) == 420.00
    assert _to_dollars(1005) == 1.0


def test_spent_milli_negates_activity() -> None:
    """Spend is the negation of YNAB's activity field."""
    category = SimpleNamespace(activity=-420000)
    assert _spent_milli(category) == 420000


def test_percent_diff_computes_ratio() -> None:
    """percent_diff is (spent - budgeted) / budgeted."""
    assert _percent_diff(300000, 420000) == (420000 - 300000) / 300000


def test_percent_diff_returns_none_for_zero_budget() -> None:
    """A zero budgeted amount makes the ratio undefined."""
    assert _percent_diff(0, 100000) is None


def test_direction_flags_over_threshold() -> None:
    """A category more than threshold over budget is 'over'."""
    assert _direction(300000, 420000, 0.10) == "over"


def test_direction_flags_under_threshold() -> None:
    """A category more than threshold under budget is 'under'."""
    assert _direction(300000, 100000, 0.10) == "under"


def test_direction_within_threshold_is_none() -> None:
    """A category within threshold is not flagged."""
    assert _direction(300000, 310000, 0.10) is None


def test_direction_zero_budget_with_spend_is_over() -> None:
    """Any spend against a $0 budget is always 'over'."""
    assert _direction(0, 1, 0.10) == "over"


def test_direction_zero_budget_with_zero_spend_is_none() -> None:
    """A $0 budget with no spend has nothing to compare."""
    assert _direction(0, 0, 0.10) is None


def test_trailing_months_walks_backward_within_year() -> None:
    """Trailing months are returned oldest-to-newest, ending at end_month."""
    result = _trailing_months(date(2024, 6, 1), 3)
    assert result == [date(2024, 4, 1), date(2024, 5, 1), date(2024, 6, 1)]


def test_trailing_months_crosses_year_boundary() -> None:
    """The window correctly rolls back across a year boundary."""
    result = _trailing_months(date(2024, 2, 1), 3)
    assert result == [date(2023, 12, 1), date(2024, 1, 1), date(2024, 2, 1)]


def test_trailing_months_single_month() -> None:
    """A window of 1 month is just the end month itself."""
    assert _trailing_months(date(2024, 6, 1), 1) == [date(2024, 6, 1)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_spend_analysis.py -v`
Expected: FAIL with `ModuleNotFoundError` or `ImportError` (module doesn't exist yet).

- [ ] **Step 3: Write minimal implementation**

Create `src/ynab_mcp/tools/spend_analysis.py`:

```python
"""flag-category-spend and analyze-category-trends tools: budget vs. actual spend analysis."""

from datetime import date

import ynab


def _to_dollars(milliunits: int) -> float:
    """Convert a YNAB milliunit amount to dollars, rounded to 2 decimals.

    Parameters
    ----------
    milliunits : int
        A YNAB amount in milliunits (1/1000 of a currency unit).

    Returns
    -------
    float
        The amount in dollars, rounded to 2 decimal places.
    """
    return round(milliunits / 1000, 2)


def _spent_milli(category: ynab.Category) -> int:
    """Return a category's spend for the month, in milliunits.

    YNAB stores ``activity`` as negative-for-spend; this negates it so
    positive values mean money spent (and negative values mean a net
    refund exceeding spend).

    Parameters
    ----------
    category : ynab.Category
        A category as returned for a single month.

    Returns
    -------
    int
        Milliunits spent (positive = spent, negative = net refund).
    """
    return -category.activity


def _percent_diff(budgeted: int, spent: int) -> float | None:
    """Compute the fractional difference between spend and budget.

    Parameters
    ----------
    budgeted : int
        Budgeted amount in milliunits.
    spent : int
        Amount spent in milliunits (see ``_spent_milli``).

    Returns
    -------
    float | None
        ``(spent - budgeted) / budgeted``, or ``None`` if ``budgeted`` is 0
        (the ratio is undefined).
    """
    if budgeted == 0:
        return None
    return (spent - budgeted) / budgeted


def _direction(budgeted: int, spent: int, threshold: float) -> str | None:
    """Classify a single category-month as over, under, or within threshold.

    A zero-budgeted category with nonzero spend is always "over" (any
    spend against no budget is unambiguous overspend). A zero-budgeted
    category with zero spend has nothing to compare and is not flagged.

    Parameters
    ----------
    budgeted : int
        Budgeted amount in milliunits.
    spent : int
        Amount spent in milliunits (see ``_spent_milli``).
    threshold : float
        Fraction of the budgeted amount beyond which spend is flagged.

    Returns
    -------
    str | None
        ``"over"``, ``"under"``, or ``None`` if within threshold (or a
        zero-budget, zero-spend category with nothing to compare).
    """
    if budgeted == 0:
        return "over" if spent > 0 else None
    percent_diff = (spent - budgeted) / budgeted
    if abs(percent_diff) < threshold:
        return None
    return "over" if percent_diff > 0 else "under"


def _trailing_months(end_month: date, months: int) -> list[date]:
    """Return the trailing N first-of-month dates ending at ``end_month``.

    Parameters
    ----------
    end_month : datetime.date
        The most recent (first-of-month) date in the window.
    months : int
        The number of months in the window.

    Returns
    -------
    list[datetime.date]
        First-of-month dates, oldest first, ending with ``end_month``.
    """
    result = []
    year, month = end_month.year, end_month.month
    for _ in range(months):
        result.append(date(year, month, 1))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return list(reversed(result))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_spend_analysis.py -v`
Expected: PASS (12 tests).

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/tools/spend_analysis.py tests/test_tools_spend_analysis.py
git commit -m "Add pure helper functions for spend analysis (#13)"
git push
```

---

### Task 2: `_fetch_month_categories` (API fetch + hidden/deleted filtering)

**Files:**
- Modify: `src/ynab_mcp/tools/spend_analysis.py`
- Test: `tests/test_tools_spend_analysis.py`

**Interfaces:**
- Consumes: `ynab.MonthsApi`, `translate_api_exception` (from `ynab_mcp.errors`).
- Produces: `_fetch_month_categories(client: ynab.ApiClient, budget_id: str, month: date) -> list[ynab.Category]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tools_spend_analysis.py`:

```python
import ynab
from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

from ynab_mcp.tools.spend_analysis import _fetch_month_categories


def test_fetch_month_categories_calls_get_plan_month(mocker: MockerFixture) -> None:
    """The fetch calls MonthsApi.get_plan_month with the given month."""
    client = mocker.Mock()
    months_api = mocker.patch("ynab_mcp.tools.spend_analysis.ynab.MonthsApi")
    visible = SimpleNamespace(id="cat-1", hidden=False, deleted=False)
    months_api.return_value.get_plan_month.return_value = SimpleNamespace(
        data=SimpleNamespace(month=SimpleNamespace(categories=[visible]))
    )

    result = _fetch_month_categories(client, "budget-1", date(2024, 3, 1))

    assert result == [visible]
    months_api.return_value.get_plan_month.assert_called_once_with(
        plan_id="budget-1", month=date(2024, 3, 1)
    )


def test_fetch_month_categories_excludes_hidden_and_deleted(
    mocker: MockerFixture,
) -> None:
    """Hidden and deleted categories are filtered out."""
    client = mocker.Mock()
    months_api = mocker.patch("ynab_mcp.tools.spend_analysis.ynab.MonthsApi")
    visible = SimpleNamespace(id="cat-1", hidden=False, deleted=False)
    hidden = SimpleNamespace(id="cat-2", hidden=True, deleted=False)
    deleted = SimpleNamespace(id="cat-3", hidden=False, deleted=True)
    months_api.return_value.get_plan_month.return_value = SimpleNamespace(
        data=SimpleNamespace(month=SimpleNamespace(categories=[visible, hidden, deleted]))
    )

    result = _fetch_month_categories(client, "budget-1", date(2024, 3, 1))

    assert result == [visible]


def test_fetch_month_categories_raises_tool_error_on_api_exception(
    mocker: MockerFixture,
) -> None:
    """An ApiException from the SDK surfaces as a ToolError."""
    client = mocker.Mock()
    months_api = mocker.patch("ynab_mcp.tools.spend_analysis.ynab.MonthsApi")
    months_api.return_value.get_plan_month.side_effect = ynab.ApiException(
        status=404,
        reason="Not Found",
        body='{"error": {"id": "404", "name": "not_found", '
        '"detail": "Budget not found"}}',
    )

    with raises(ToolError, match="Budget not found"):
        _fetch_month_categories(client, "missing-budget", date(2024, 3, 1))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_spend_analysis.py -v`
Expected: FAIL with `ImportError: cannot import name '_fetch_month_categories'`.

- [ ] **Step 3: Write minimal implementation**

Add to `src/ynab_mcp/tools/spend_analysis.py` (after the imports, add `from ynab_mcp.errors import translate_api_exception`; place the function after `_trailing_months`):

```python
from ynab_mcp.errors import translate_api_exception


def _fetch_month_categories(
    client: ynab.ApiClient, budget_id: str, month: date
) -> list[ynab.Category]:
    """Fetch a month's categories, excluding hidden and deleted ones.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id (translated to the SDK's ``plan_id``).
    month : datetime.date
        The first-of-month date to fetch.

    Returns
    -------
    list[ynab.Category]
        Every non-hidden, non-deleted category for the month.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If the YNAB API request fails.
    """
    api = ynab.MonthsApi(client)
    try:
        response = api.get_plan_month(plan_id=budget_id, month=month)
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
Expected: PASS (15 tests).

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/tools/spend_analysis.py tests/test_tools_spend_analysis.py
git commit -m "Add month-category fetch helper for spend analysis (#13)"
git push
```

---

### Task 3: `flag_category_spend` plain function

**Files:**
- Modify: `src/ynab_mcp/tools/spend_analysis.py`
- Test: `tests/test_tools_spend_analysis.py`

**Interfaces:**
- Consumes: `_fetch_month_categories`, `_spent_milli`, `_direction`, `_percent_diff`, `_to_dollars` (Tasks 1-2), `parse_month` (from `ynab_mcp.tools.months`).
- Produces: `flag_category_spend(client: ynab.ApiClient, budget_id: str, month: str, threshold: float = 0.10) -> list[dict[str, object]]`

Each returned dict has keys: `category_id`, `category_name`, `budgeted` (float dollars), `activity` (float dollars), `direction` (`"over"` | `"under"`), `percent_diff` (float | None), `reason` (str).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tools_spend_analysis.py`:

```python
from ynab_mcp.tools.spend_analysis import flag_category_spend


def _category(
    category_id: str = "cat-1",
    name: str = "Groceries",
    budgeted: int = 300000,
    activity: int = -420000,
    hidden: bool = False,
    deleted: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=category_id,
        name=name,
        budgeted=budgeted,
        activity=activity,
        hidden=hidden,
        deleted=deleted,
    )


def _mock_month_categories(mocker: MockerFixture, categories: list) -> None:
    months_api = mocker.patch("ynab_mcp.tools.spend_analysis.ynab.MonthsApi")
    months_api.return_value.get_plan_month.return_value = SimpleNamespace(
        data=SimpleNamespace(month=SimpleNamespace(categories=categories))
    )


def test_flag_category_spend_flags_over_threshold(mocker: MockerFixture) -> None:
    """A category spent well beyond budget is flagged 'over'."""
    client = mocker.Mock()
    _mock_month_categories(mocker, [_category(budgeted=300000, activity=-420000)])

    result = flag_category_spend(client, "budget-1", "2024-03-01", threshold=0.10)

    assert len(result) == 1
    flag = result[0]
    assert flag["category_id"] == "cat-1"
    assert flag["category_name"] == "Groceries"
    assert flag["budgeted"] == 300.00
    assert flag["activity"] == 420.00
    assert flag["direction"] == "over"
    assert flag["percent_diff"] == approx(0.40)
    assert "420.00" in flag["reason"]
    assert "300.00" in flag["reason"]
    assert "40%" in flag["reason"]
    assert "over" in flag["reason"]


def test_flag_category_spend_flags_under_threshold(mocker: MockerFixture) -> None:
    """A category spent well below budget is flagged 'under'."""
    client = mocker.Mock()
    _mock_month_categories(mocker, [_category(budgeted=300000, activity=-50000)])

    result = flag_category_spend(client, "budget-1", "2024-03-01", threshold=0.10)

    assert len(result) == 1
    assert result[0]["direction"] == "under"


def test_flag_category_spend_omits_within_threshold(mocker: MockerFixture) -> None:
    """A category within threshold is not included in the output."""
    client = mocker.Mock()
    _mock_month_categories(mocker, [_category(budgeted=300000, activity=-310000)])

    result = flag_category_spend(client, "budget-1", "2024-03-01", threshold=0.10)

    assert result == []


def test_flag_category_spend_zero_budget_with_activity_always_flagged(
    mocker: MockerFixture,
) -> None:
    """A $0-budgeted category with any spend is always flagged 'over'."""
    client = mocker.Mock()
    _mock_month_categories(mocker, [_category(budgeted=0, activity=-1000)])

    result = flag_category_spend(client, "budget-1", "2024-03-01", threshold=0.10)

    assert len(result) == 1
    assert result[0]["direction"] == "over"
    assert result[0]["percent_diff"] is None
    assert "no budget allocated" in result[0]["reason"]


def test_flag_category_spend_zero_budget_zero_activity_not_flagged(
    mocker: MockerFixture,
) -> None:
    """A $0-budgeted, unused category is not flagged."""
    client = mocker.Mock()
    _mock_month_categories(mocker, [_category(budgeted=0, activity=0)])

    result = flag_category_spend(client, "budget-1", "2024-03-01", threshold=0.10)

    assert result == []


def test_flag_category_spend_excludes_hidden(mocker: MockerFixture) -> None:
    """A hidden category is excluded even if over threshold."""
    client = mocker.Mock()
    _mock_month_categories(
        mocker, [_category(budgeted=300000, activity=-420000, hidden=True)]
    )

    result = flag_category_spend(client, "budget-1", "2024-03-01", threshold=0.10)

    assert result == []


def test_flag_category_spend_rejects_invalid_month(mocker: MockerFixture) -> None:
    """An unparseable month raises a ToolError."""
    client = mocker.Mock()

    with raises(ToolError, match="Invalid month"):
        flag_category_spend(client, "budget-1", "not-a-date")


def test_flag_category_spend_rejects_negative_threshold(mocker: MockerFixture) -> None:
    """A negative threshold raises a ToolError."""
    client = mocker.Mock()

    with raises(ToolError, match="threshold"):
        flag_category_spend(client, "budget-1", "2024-03-01", threshold=-0.1)


def test_flag_category_spend_raises_tool_error_on_api_exception(
    mocker: MockerFixture,
) -> None:
    """An ApiException from the SDK surfaces as a ToolError."""
    client = mocker.Mock()
    months_api = mocker.patch("ynab_mcp.tools.spend_analysis.ynab.MonthsApi")
    months_api.return_value.get_plan_month.side_effect = ynab.ApiException(
        status=404,
        reason="Not Found",
        body='{"error": {"id": "404", "name": "not_found", '
        '"detail": "Budget not found"}}',
    )

    with raises(ToolError, match="Budget not found"):
        flag_category_spend(client, "missing-budget", "2024-03-01")
```

Add this import near the top of the test file (alongside the existing `from pytest import raises`):

```python
from pytest import approx
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_spend_analysis.py -v`
Expected: FAIL with `ImportError: cannot import name 'flag_category_spend'`.

- [ ] **Step 3: Write minimal implementation**

Add to `src/ynab_mcp/tools/spend_analysis.py` (add `from fastmcp.exceptions import ToolError` and `from ynab_mcp.tools.months import parse_month` to the imports):

```python
from fastmcp.exceptions import ToolError

from ynab_mcp.tools.months import parse_month


def flag_category_spend(
    client: ynab.ApiClient, budget_id: str, month: str, threshold: float = 0.10
) -> list[dict[str, object]]:
    """Flag categories whose spend is beyond threshold of budgeted for a month.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id (translated to the SDK's ``plan_id``).
    month : str
        An ISO-formatted month (e.g. ``"2024-01-01"``) or the literal
        string ``"current"``.
    threshold : float, optional
        Fraction of the budgeted amount beyond which spend is flagged, by
        default ``0.10``.

    Returns
    -------
    list[dict[str, object]]
        One entry per flagged category (categories within threshold are
        omitted), each with ``category_id``, ``category_name``,
        ``budgeted``, ``activity`` (dollars), ``direction``
        (``"over"``/``"under"``), ``percent_diff``, and a plain-language
        ``reason``.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If ``threshold`` is negative, ``month`` is invalid, or the YNAB
        API request fails.
    """
    if threshold < 0:
        raise ToolError("threshold must be >= 0.")
    resolved_month = parse_month(month)
    categories = _fetch_month_categories(client, budget_id, resolved_month)

    flags: list[dict[str, object]] = []
    for category in categories:
        spent = _spent_milli(category)
        direction = _direction(category.budgeted, spent, threshold)
        if direction is None:
            continue
        percent_diff = _percent_diff(category.budgeted, spent)
        budgeted_dollars = _to_dollars(category.budgeted)
        spent_dollars = _to_dollars(spent)
        if category.budgeted == 0:
            reason = (
                f"Spent ${spent_dollars:.2f} against a $0.00 budget "
                "(no budget allocated)."
            )
        else:
            reason = (
                f"Spent ${spent_dollars:.2f} against a ${budgeted_dollars:.2f} "
                f"budget ({abs(percent_diff):.0%} {direction})."
            )
        flags.append(
            {
                "category_id": category.id,
                "category_name": category.name,
                "budgeted": budgeted_dollars,
                "activity": spent_dollars,
                "direction": direction,
                "percent_diff": percent_diff,
                "reason": reason,
            }
        )
    return flags
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_spend_analysis.py -v`
Expected: PASS (24 tests).

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/tools/spend_analysis.py tests/test_tools_spend_analysis.py
git commit -m "Add flag_category_spend for single-month overspend detection (#13)"
git push
```

---

### Task 4: Register `flag-category-spend` tool

**Files:**
- Modify: `src/ynab_mcp/tools/spend_analysis.py`
- Modify: `src/ynab_mcp/server.py`
- Modify: `tests/test_server.py`

**Interfaces:**
- Consumes: `flag_category_spend` (Task 3), `resolve_budget_id` (from `ynab_mcp.client`).
- Produces: `register(mcp: FastMCP, client: ynab.ApiClient, settings: Settings) -> None`, registering the `flag-category-spend` tool (the `analyze-category-trends` tool is added to this same `register` in Task 6).

- [ ] **Step 1: Write the failing test**

Modify `tests/test_server.py`'s `test_build_server_registers_all_other_tools` — add `"flag-category-spend"` to the expected set:

```python
def test_build_server_registers_all_other_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every non-list-budgets tool is always registered."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("YNAB_PAT", "test-token")
    monkeypatch.setenv("YNAB_DEFAULT_BUDGET_ID", "budget-123")

    mcp = build_server()

    tool_names = _list_tool_names(mcp)
    assert tool_names == {
        "list-accounts",
        "list-categories",
        "list-transactions",
        "get-month-info",
        "list-payees",
        "lookup-entity-by-id",
        "flag-category-spend",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_server.py::test_build_server_registers_all_other_tools -v`
Expected: FAIL — actual tool set is missing `"flag-category-spend"`.

- [ ] **Step 3: Write minimal implementation**

Add to `src/ynab_mcp/tools/spend_analysis.py` (add `from fastmcp import FastMCP`, `from ynab_mcp.client import resolve_budget_id`, `from ynab_mcp.config import Settings` to the imports):

```python
from fastmcp import FastMCP

from ynab_mcp.client import resolve_budget_id
from ynab_mcp.config import Settings


def register(mcp: FastMCP, client: ynab.ApiClient, settings: Settings) -> None:
    """Register the spend-analysis tools on ``mcp``.

    Parameters
    ----------
    mcp : fastmcp.FastMCP
        The server to register the tools on.
    client : ynab.ApiClient
        A configured YNAB API client.
    settings : Settings
        The server's parsed configuration, used to resolve a default budget
        id when the caller omits one.
    """

    @mcp.tool(name="flag-category-spend")
    def flag_category_spend_tool(
        month: str, threshold: float = 0.10, budget_id: str | None = None
    ) -> list[dict[str, object]]:
        """Flag categories whose spend is beyond threshold of budgeted for a month.

        Parameters
        ----------
        month : str
            An ISO-formatted month (e.g. ``"2024-01-01"``) or the literal
            string ``"current"``.
        threshold : float, optional
            Fraction of the budgeted amount beyond which spend is flagged,
            by default ``0.10``.
        budget_id : str | None, optional
            The YNAB budget id, by default ``None`` (falls back to
            ``YNAB_DEFAULT_BUDGET_ID``).
        """
        resolved_budget_id = resolve_budget_id(budget_id, settings)
        return flag_category_spend(client, resolved_budget_id, month, threshold)
```

Modify `src/ynab_mcp/server.py`: add `spend_analysis` to the `tools` import and call its `register`:

```python
from ynab_mcp.tools import (
    accounts,
    budgets,
    categories,
    lookup,
    months,
    payees,
    spend_analysis,
    transactions,
)
```

```python
    accounts.register(mcp, client, settings)
    categories.register(mcp, client, settings)
    transactions.register(mcp, client, settings)
    months.register(mcp, client, settings)
    payees.register(mcp, client, settings)
    lookup.register(mcp, client, settings)
    spend_analysis.register(mcp, client, settings)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_server.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/tools/spend_analysis.py src/ynab_mcp/server.py tests/test_server.py
git commit -m "Register flag-category-spend tool on the server (#13)"
git push
```

---

### Task 5: `analyze_category_trends` plain function

**Files:**
- Modify: `src/ynab_mcp/tools/spend_analysis.py`
- Test: `tests/test_tools_spend_analysis.py`

**Interfaces:**
- Consumes: `_trailing_months`, `_fetch_month_categories`, `_spent_milli`, `_direction`, `_to_dollars` (Tasks 1-2), `parse_month` (from `ynab_mcp.tools.months`).
- Produces: `analyze_category_trends(client: ynab.ApiClient, budget_id: str, months: int = 6, end_month: str = "current", overspend_threshold: float = 0.10, majority_ratio: float = 0.5) -> list[dict[str, object]]`

Each returned dict has keys: `category_id`, `category_name`, `trend` (`"rising_overspend"` | `"persistent_underspend"` | `"insufficient_history"`), `reason` (str), plus for non-`insufficient_history` entries: `budgeted` (float dollars) and either `months_over_threshold` or `months_under_threshold` plus `months_in_window` (both int).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tools_spend_analysis.py`:

```python
from ynab_mcp.tools.spend_analysis import analyze_category_trends


def _mock_month_sequence(mocker: MockerFixture, monthly_categories: list[list]) -> None:
    """Mock get_plan_month to return one category list per call, in order."""
    months_api = mocker.patch("ynab_mcp.tools.spend_analysis.ynab.MonthsApi")
    months_api.return_value.get_plan_month.side_effect = [
        SimpleNamespace(data=SimpleNamespace(month=SimpleNamespace(categories=cats)))
        for cats in monthly_categories
    ]


def test_analyze_category_trends_detects_rising_overspend(
    mocker: MockerFixture,
) -> None:
    """A category with a rising budget, overspent in most months, is flagged."""
    client = mocker.Mock()
    # 6 months, budgeted rises 200k -> 350k, overspent in 4 of 6 months.
    budgets = [200000, 220000, 240000, 260000, 300000, 350000]
    activities = [-250000, -200000, -300000, -210000, -400000, -420000]
    monthly = [
        [_category(budgeted=b, activity=a)] for b, a in zip(budgets, activities)
    ]
    _mock_month_sequence(mocker, monthly)

    result = analyze_category_trends(
        client, "budget-1", months=6, end_month="2024-06-01"
    )

    assert len(result) == 1
    flag = result[0]
    assert flag["trend"] == "rising_overspend"
    assert flag["category_id"] == "cat-1"
    assert flag["budgeted"] == 350.00
    assert flag["months_over_threshold"] >= 3
    assert flag["months_in_window"] == 6
    assert "rising_overspend" not in flag["reason"]
    assert "overspent" in flag["reason"]


def test_analyze_category_trends_detects_persistent_underspend(
    mocker: MockerFixture,
) -> None:
    """A category consistently underspent is flagged, regardless of budget trend."""
    client = mocker.Mock()
    monthly = [
        [_category(budgeted=300000, activity=-50000)] for _ in range(6)
    ]
    _mock_month_sequence(mocker, monthly)

    result = analyze_category_trends(
        client, "budget-1", months=6, end_month="2024-06-01"
    )

    assert len(result) == 1
    flag = result[0]
    assert flag["trend"] == "persistent_underspend"
    assert flag["months_under_threshold"] == 6
    assert flag["months_in_window"] == 6


def test_analyze_category_trends_ignores_single_anomalous_month(
    mocker: MockerFixture,
) -> None:
    """One anomalous overspend month among six does not trigger a flag."""
    client = mocker.Mock()
    # Only 1 of 6 months is over threshold; well within threshold otherwise.
    activities = [-305000, -305000, -305000, -305000, -305000, -600000]
    monthly = [
        [_category(budgeted=300000, activity=a)] for a in activities
    ]
    _mock_month_sequence(mocker, monthly)

    result = analyze_category_trends(
        client, "budget-1", months=6, end_month="2024-06-01"
    )

    assert result == []


def test_analyze_category_trends_flags_insufficient_history(
    mocker: MockerFixture,
) -> None:
    """A category present in only the 2 most recent of 6 months is skipped."""
    client = mocker.Mock()
    empty: list = []
    present = [_category(budgeted=300000, activity=-300000)]
    monthly = [empty, empty, empty, empty, present, present]
    _mock_month_sequence(mocker, monthly)

    result = analyze_category_trends(
        client, "budget-1", months=6, end_month="2024-06-01"
    )

    assert len(result) == 1
    flag = result[0]
    assert flag["trend"] == "insufficient_history"
    assert flag["category_id"] == "cat-1"
    assert "2/6" in flag["reason"]


def test_analyze_category_trends_excludes_hidden(mocker: MockerFixture) -> None:
    """A category hidden in every month never appears in trend output."""
    client = mocker.Mock()
    monthly = [
        [_category(budgeted=300000, activity=-50000, hidden=True)] for _ in range(6)
    ]
    _mock_month_sequence(mocker, monthly)

    result = analyze_category_trends(
        client, "budget-1", months=6, end_month="2024-06-01"
    )

    assert result == []


def test_analyze_category_trends_rejects_invalid_months(mocker: MockerFixture) -> None:
    """months < 1 raises a ToolError."""
    client = mocker.Mock()

    with raises(ToolError, match="months"):
        analyze_category_trends(client, "budget-1", months=0)


def test_analyze_category_trends_rejects_invalid_majority_ratio(
    mocker: MockerFixture,
) -> None:
    """majority_ratio outside (0, 1] raises a ToolError."""
    client = mocker.Mock()

    with raises(ToolError, match="majority_ratio"):
        analyze_category_trends(client, "budget-1", majority_ratio=1.5)


def test_analyze_category_trends_raises_tool_error_on_api_exception(
    mocker: MockerFixture,
) -> None:
    """An ApiException on any fetched month surfaces as a ToolError."""
    client = mocker.Mock()
    months_api = mocker.patch("ynab_mcp.tools.spend_analysis.ynab.MonthsApi")
    months_api.return_value.get_plan_month.side_effect = ynab.ApiException(
        status=404,
        reason="Not Found",
        body='{"error": {"id": "404", "name": "not_found", '
        '"detail": "Budget not found"}}',
    )

    with raises(ToolError, match="Budget not found"):
        analyze_category_trends(client, "missing-budget", months=6, end_month="2024-06-01")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_spend_analysis.py -v`
Expected: FAIL with `ImportError: cannot import name 'analyze_category_trends'`.

- [ ] **Step 3: Write minimal implementation**

Add to `src/ynab_mcp/tools/spend_analysis.py`:

```python
def analyze_category_trends(
    client: ynab.ApiClient,
    budget_id: str,
    months: int = 6,
    end_month: str = "current",
    overspend_threshold: float = 0.10,
    majority_ratio: float = 0.5,
) -> list[dict[str, object]]:
    """Detect multi-month overspend/underspend patterns per category.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id (translated to the SDK's ``plan_id``).
    months : int, optional
        The trailing window size in months, by default ``6``.
    end_month : str, optional
        The most recent month in the window: an ISO-formatted month or the
        literal string ``"current"``, by default ``"current"``.
    overspend_threshold : float, optional
        Fraction of budgeted beyond which a single month counts as
        over/under spent, by default ``0.10``.
    majority_ratio : float, optional
        Fraction of the window's months that must show the pattern for it
        to count as a real trend, by default ``0.5``.

    Returns
    -------
    list[dict[str, object]]
        One entry per flagged or insufficient-history category. Flagged
        entries have ``category_id``, ``category_name``, ``budgeted``
        (dollars, most recent month), ``trend``
        (``"rising_overspend"``/``"persistent_underspend"``), a
        ``months_over_threshold`` or ``months_under_threshold`` count,
        ``months_in_window``, and a plain-language ``reason``.
        Insufficient-history entries have ``category_id``,
        ``category_name``, ``trend="insufficient_history"``, and
        ``reason``.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If ``months < 1``, ``overspend_threshold < 0``, ``majority_ratio``
        is outside ``(0, 1]``, ``end_month`` is invalid, or the YNAB API
        request fails for any month in the window.
    """
    if months < 1:
        raise ToolError("months must be >= 1.")
    if overspend_threshold < 0:
        raise ToolError("overspend_threshold must be >= 0.")
    if not (0 < majority_ratio <= 1):
        raise ToolError("majority_ratio must be > 0 and <= 1.")

    resolved_end_month = parse_month(end_month)
    window_months = _trailing_months(resolved_end_month, months)
    monthly_categories = [
        _fetch_month_categories(client, budget_id, m) for m in window_months
    ]
    month_maps = [{c.id: c for c in cats} for cats in monthly_categories]
    all_category_ids = {c.id: c.name for cats in monthly_categories for c in cats}

    results: list[dict[str, object]] = []
    for category_id in all_category_ids:
        trailing_count = 0
        for month_map in reversed(month_maps):
            if category_id in month_map:
                trailing_count += 1
            else:
                break

        if trailing_count < months:
            name = next(
                m[category_id].name for m in reversed(month_maps) if category_id in m
            )
            results.append(
                {
                    "category_id": category_id,
                    "category_name": name,
                    "trend": "insufficient_history",
                    "reason": (
                        f"Insufficient history ({trailing_count}/{months} months)."
                    ),
                }
            )
            continue

        latest = month_maps[-1][category_id]
        earliest = month_maps[0][category_id]

        months_over = 0
        months_under = 0
        for month_map in month_maps:
            category = month_map[category_id]
            direction = _direction(
                category.budgeted, _spent_milli(category), overspend_threshold
            )
            if direction == "over":
                months_over += 1
            elif direction == "under":
                months_under += 1

        rising = latest.budgeted > earliest.budgeted
        if rising and months_over / months >= majority_ratio:
            results.append(
                {
                    "category_id": category_id,
                    "category_name": latest.name,
                    "budgeted": _to_dollars(latest.budgeted),
                    "trend": "rising_overspend",
                    "months_over_threshold": months_over,
                    "months_in_window": months,
                    "reason": (
                        f"Budget raised from ${_to_dollars(earliest.budgeted):.2f} "
                        f"to ${_to_dollars(latest.budgeted):.2f} over {months} "
                        f"months but overspent in {months_over}/{months} months."
                    ),
                }
            )
        elif months_under / months >= majority_ratio:
            results.append(
                {
                    "category_id": category_id,
                    "category_name": latest.name,
                    "budgeted": _to_dollars(latest.budgeted),
                    "trend": "persistent_underspend",
                    "months_under_threshold": months_under,
                    "months_in_window": months,
                    "reason": (
                        f"Underspent in {months_under}/{months} months "
                        f"(budget ${_to_dollars(latest.budgeted):.2f})."
                    ),
                }
            )

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_spend_analysis.py -v`
Expected: PASS (32 tests).

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/tools/spend_analysis.py tests/test_tools_spend_analysis.py
git commit -m "Add analyze_category_trends for multi-month pattern detection (#13)"
git push
```

---

### Task 6: Register `analyze-category-trends` tool

**Files:**
- Modify: `src/ynab_mcp/tools/spend_analysis.py`
- Modify: `tests/test_server.py`

**Interfaces:**
- Consumes: `analyze_category_trends` (Task 5), the existing `register` function body (Task 4).
- Produces: `register` now registers both `flag-category-spend` and `analyze-category-trends`.

- [ ] **Step 1: Write the failing test**

Modify `tests/test_server.py`'s expected tool set again:

```python
    assert tool_names == {
        "list-accounts",
        "list-categories",
        "list-transactions",
        "get-month-info",
        "list-payees",
        "lookup-entity-by-id",
        "flag-category-spend",
        "analyze-category-trends",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_server.py::test_build_server_registers_all_other_tools -v`
Expected: FAIL — actual tool set is missing `"analyze-category-trends"`.

- [ ] **Step 3: Write minimal implementation**

Add to `register` in `src/ynab_mcp/tools/spend_analysis.py`, after the `flag_category_spend_tool` definition:

```python
    @mcp.tool(name="analyze-category-trends")
    def analyze_category_trends_tool(
        months: int = 6,
        end_month: str = "current",
        overspend_threshold: float = 0.10,
        majority_ratio: float = 0.5,
        budget_id: str | None = None,
    ) -> list[dict[str, object]]:
        """Detect multi-month overspend/underspend patterns per category.

        Parameters
        ----------
        months : int, optional
            The trailing window size in months, by default ``6``.
        end_month : str, optional
            The most recent month in the window: an ISO-formatted month or
            the literal string ``"current"``, by default ``"current"``.
        overspend_threshold : float, optional
            Fraction of budgeted beyond which a single month counts as
            over/under spent, by default ``0.10``.
        majority_ratio : float, optional
            Fraction of the window's months that must show the pattern for
            it to count as a real trend, by default ``0.5``.
        budget_id : str | None, optional
            The YNAB budget id, by default ``None`` (falls back to
            ``YNAB_DEFAULT_BUDGET_ID``).
        """
        resolved_budget_id = resolve_budget_id(budget_id, settings)
        return analyze_category_trends(
            client,
            resolved_budget_id,
            months=months,
            end_month=end_month,
            overspend_threshold=overspend_threshold,
            majority_ratio=majority_ratio,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_server.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/tools/spend_analysis.py tests/test_server.py
git commit -m "Register analyze-category-trends tool on the server (#13)"
git push
```

---

### Task 7: Full quality gate

**Files:** none (verification only; fix inline if issues are found).

**Interfaces:**
- Consumes: the complete `spend_analysis.py` module and its tests from Tasks 1-6.
- Produces: a green `make pr_check` run.

- [ ] **Step 1: Run the full lint + test gate**

Run: `make pr_check`
Expected: PASS — formatting, lint, type-check, and the full test suite (including `tests/test_tools_spend_analysis.py` and `tests/test_server.py`) all succeed with zero failures.

- [ ] **Step 2: Fix any issues found**

If `make lint` reports formatting or type issues (e.g. a missing type annotation, an unused import), fix them directly in `src/ynab_mcp/tools/spend_analysis.py` or the test file. If `make tests` reports failures not caught by earlier tasks, treat them as a genuine gap and fix the implementation, not the test.

- [ ] **Step 3: Re-run to confirm green**

Run: `make pr_check`
Expected: PASS, no changes needed (or PASS after the Step 2 fix).

- [ ] **Step 4: Commit any fixes**

Only if Step 2 required changes:

```bash
git add -u
git commit -m "Fix lint/type issues found in full quality gate (#13)"
git push
```
