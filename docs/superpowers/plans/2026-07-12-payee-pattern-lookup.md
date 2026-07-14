# Payee/Transaction Pattern Lookup Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new `find-payee-transactions` MCP tool that takes a payee name/substring, fuzzy-matches it against a budget's payees, and returns per-payee transaction-pattern stats (frequency, typical amount, amount range, most common category, recurring-charge guess).

**Architecture:** A new `src/ynab_mcp/tools/payee_patterns.py` module, following the existing `tools/*.py` pattern (plain testable function + thin `register()`). It imports and calls `list_payees` (`tools/payees.py`) and `list_transactions` (`tools/transactions.py`) directly rather than touching the YNAB SDK itself — the same cross-tool-module import pattern `tools/lookup.py` already uses for `tools/months.py`'s `parse_month`. Matching is substring-first with a `difflib.SequenceMatcher` fuzzy fallback; grouping is one summary per matched payee name (not pooled); the recurring-charge heuristic is count (≥3) + amount consistency (no date-interval analysis).

**Tech Stack:** Python 3.13, FastMCP v3, official `ynab` SDK, `pytest` + `pytest-mock`, stdlib `difflib`/`statistics`/`collections.Counter` (no new dependency).

## Global Constraints

- Fuzzy matching uses stdlib `difflib.SequenceMatcher` only — no new runtime dependency (`rapidfuzz`/`thefuzz` explicitly rejected during brainstorming).
- Response is stats-only per matched payee — no raw transaction list nested in the result.
- `fuzzy_threshold` is a plain-function parameter (default `0.6`), not exposed as an MCP tool parameter.
- `typical_amount` and `amount_range` are in YNAB milliunits (`int`), matching `ynab.TransactionDetail.amount`'s convention — never converted to dollars except inside the human-readable `recurring_guess` string.
- Recurring-charge heuristic: `transaction_count >= 3` AND every amount within tolerance (`max(10% of |typical_amount|, 1000 milliunits)`) of the median. No date-interval/regularity analysis.
- A matched payee with zero transactions is excluded from the result (no meaningful "pattern" to report for a payee with no transaction history).
- Empty/whitespace `payee_query` raises `fastmcp.exceptions.ToolError`.
- Full numpy-convention docstrings on every function (including private helpers) — matches this codebase's established convention (see `errors.py`'s `_extract_detail`), and is required for `make lint` (`ruff` `D` rules + `pydocstyle` numpy convention configured in `pyproject.toml`).
- `mypy` runs with `disallow_untyped_defs = true` — every function signature (including private helpers) needs full type annotations.

---

### Task 1: Payee matching helper

**Files:**
- Create: `src/ynab_mcp/tools/payee_patterns.py`
- Test: `tests/test_tools_payee_patterns.py`

**Interfaces:**
- Produces: `MatchType = Literal["exact", "substring", "fuzzy"]`, `_MatchedPayee` dataclass (`payee: ynab.Payee`, `match_type: MatchType`, `match_score: float | None`), `_match_payees(payees: list[ynab.Payee], payee_query: str, fuzzy_threshold: float) -> list[_MatchedPayee]`.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for ynab_mcp.tools.payee_patterns."""

from types import SimpleNamespace

from ynab_mcp.tools.payee_patterns import _match_payees


def test_match_payees_exact_match() -> None:
    """A payee name equal to the query (case-insensitive) matches exactly."""
    payees = [
        SimpleNamespace(id="p1", name="Amazon.com"),
        SimpleNamespace(id="p2", name="Starbucks"),
    ]

    matches = _match_payees(payees, "amazon.com", fuzzy_threshold=0.6)

    assert len(matches) == 1
    assert matches[0].payee.id == "p1"
    assert matches[0].match_type == "exact"
    assert matches[0].match_score is None


def test_match_payees_substring_match() -> None:
    """A query that is a substring of the payee name matches by substring."""
    payees = [SimpleNamespace(id="p1", name="AMZN Mktp US Amazon")]

    matches = _match_payees(payees, "amazon", fuzzy_threshold=0.6)

    assert len(matches) == 1
    assert matches[0].match_type == "substring"
    assert matches[0].match_score is None


def test_match_payees_fuzzy_match() -> None:
    """A payee name that doesn't contain the query but scores above the
    threshold matches by fuzzy similarity."""
    payees = [SimpleNamespace(id="p1", name="Wal-Mart #1234")]

    matches = _match_payees(payees, "walmart", fuzzy_threshold=0.6)

    assert len(matches) == 1
    assert matches[0].match_type == "fuzzy"
    assert matches[0].match_score is not None
    assert matches[0].match_score >= 0.6


def test_match_payees_no_match() -> None:
    """A payee name scoring below the fuzzy threshold and not containing
    the query is excluded entirely."""
    payees = [SimpleNamespace(id="p1", name="Netflix")]

    matches = _match_payees(payees, "walmart", fuzzy_threshold=0.6)

    assert matches == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_payee_patterns.py -v`
Expected: FAIL (collection error) with `ModuleNotFoundError: No module named 'ynab_mcp.tools.payee_patterns'`

- [ ] **Step 3: Write the minimal implementation**

Create `src/ynab_mcp/tools/payee_patterns.py`:

```python
"""find-payee-transactions tool: locate a payee's transaction patterns."""

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

import ynab

MatchType = Literal["exact", "substring", "fuzzy"]


@dataclass(frozen=True)
class _MatchedPayee:
    """A payee that matched a lookup query, and how it matched.

    Parameters
    ----------
    payee : ynab.Payee
        The matched payee record.
    match_type : MatchType
        Whether the match was exact, substring, or fuzzy.
    match_score : float | None
        The ``difflib`` similarity ratio, set only when ``match_type`` is
        ``"fuzzy"``.
    """

    payee: ynab.Payee
    match_type: MatchType
    match_score: float | None


def _match_payees(
    payees: list[ynab.Payee], payee_query: str, fuzzy_threshold: float
) -> list[_MatchedPayee]:
    """Match payees against a query, case-insensitively.

    Checks each payee name for an exact match, then a substring match in
    either direction, then falls back to a ``difflib`` similarity ratio
    for names that don't literally contain the query -- catching
    abbreviations like "AMZN Mktp US" for a search on "amazon" that a
    plain substring check would miss.

    Parameters
    ----------
    payees : list[ynab.Payee]
        Every payee in the budget.
    payee_query : str
        The caller's search term.
    fuzzy_threshold : float
        The minimum ``difflib.SequenceMatcher.ratio()`` for a name that
        doesn't contain the query to still count as a match.

    Returns
    -------
    list[_MatchedPayee]
        Every payee that matched, in payee order.
    """
    query = payee_query.strip().lower()
    matches: list[_MatchedPayee] = []
    for payee in payees:
        name = payee.name.lower()
        if name == query:
            matches.append(_MatchedPayee(payee, "exact", None))
        elif query in name or name in query:
            matches.append(_MatchedPayee(payee, "substring", None))
        else:
            score = SequenceMatcher(None, query, name).ratio()
            if score >= fuzzy_threshold:
                matches.append(_MatchedPayee(payee, "fuzzy", score))
    return matches
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_payee_patterns.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/tools/payee_patterns.py tests/test_tools_payee_patterns.py
git commit -m "feat: add payee matching helper for find-payee-transactions"
git push
```

---

### Task 2: Transaction-stats aggregation helpers

**Files:**
- Modify: `src/ynab_mcp/tools/payee_patterns.py`
- Test: `tests/test_tools_payee_patterns.py`

**Interfaces:**
- Consumes: `MatchType`, `_MatchedPayee` from Task 1.
- Produces: `AmountRange` dataclass (`min: int`, `max: int`), `PayeeGroupSummary` dataclass (`payee_id: str`, `payee_name: str`, `match_type: MatchType`, `match_score: float | None`, `transaction_count: int`, `typical_amount: int`, `amount_range: AmountRange`, `most_common_category: str | None`, `recurring_guess: str | None`), `_summarize_group(matched: _MatchedPayee, transactions: list[ynab.TransactionDetail]) -> PayeeGroupSummary`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tools_payee_patterns.py`:

```python
from ynab_mcp.tools.payee_patterns import _MatchedPayee, _summarize_group


def _transaction(amount: int, category_name: str | None) -> SimpleNamespace:
    return SimpleNamespace(amount=amount, category_name=category_name)


def test_summarize_group_computes_stats() -> None:
    """Transaction count, typical amount, amount range, and most common
    category are computed correctly from a matched payee's transactions."""
    matched = _MatchedPayee(
        payee=SimpleNamespace(id="p1", name="Coffee Shop"),
        match_type="exact",
        match_score=None,
    )
    transactions = [
        _transaction(-5000, "Dining Out"),
        _transaction(-5500, "Dining Out"),
        _transaction(-4500, "Groceries"),
    ]

    summary = _summarize_group(matched, transactions)

    assert summary.payee_id == "p1"
    assert summary.payee_name == "Coffee Shop"
    assert summary.match_type == "exact"
    assert summary.transaction_count == 3
    assert summary.typical_amount == -5000
    assert summary.amount_range.min == -5500
    assert summary.amount_range.max == -4500
    assert summary.most_common_category == "Dining Out"


def test_summarize_group_no_common_category_when_uncategorized() -> None:
    """most_common_category is None when no transaction has a category."""
    matched = _MatchedPayee(
        payee=SimpleNamespace(id="p1", name="Coffee Shop"),
        match_type="exact",
        match_score=None,
    )
    transactions = [_transaction(-5000, None), _transaction(-5000, None)]

    summary = _summarize_group(matched, transactions)

    assert summary.most_common_category is None


def test_summarize_group_recurring_guess_fires() -> None:
    """recurring_guess is set when >=3 transactions have consistent
    amounts."""
    matched = _MatchedPayee(
        payee=SimpleNamespace(id="p1", name="Streaming Service"),
        match_type="exact",
        match_score=None,
    )
    transactions = [
        _transaction(-14990, "Entertainment"),
        _transaction(-14990, "Entertainment"),
        _transaction(-14990, "Entertainment"),
    ]

    summary = _summarize_group(matched, transactions)

    assert summary.recurring_guess is not None
    assert "14.99" in summary.recurring_guess
    assert "3" in summary.recurring_guess


def test_summarize_group_recurring_guess_does_not_fire_below_count() -> None:
    """recurring_guess is None with fewer than 3 transactions, even if
    amounts are consistent."""
    matched = _MatchedPayee(
        payee=SimpleNamespace(id="p1", name="Streaming Service"),
        match_type="exact",
        match_score=None,
    )
    transactions = [_transaction(-14990, None), _transaction(-14990, None)]

    summary = _summarize_group(matched, transactions)

    assert summary.recurring_guess is None


def test_summarize_group_recurring_guess_does_not_fire_inconsistent_amounts() -> None:
    """recurring_guess is None when amounts vary too much, even with
    enough transactions."""
    matched = _MatchedPayee(
        payee=SimpleNamespace(id="p1", name="Grocery Store"),
        match_type="exact",
        match_score=None,
    )
    transactions = [
        _transaction(-2000, None),
        _transaction(-9000, None),
        _transaction(-15000, None),
    ]

    summary = _summarize_group(matched, transactions)

    assert summary.recurring_guess is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_payee_patterns.py -v`
Expected: FAIL with `ImportError: cannot import name '_summarize_group'`

- [ ] **Step 3: Write the minimal implementation**

Append to `src/ynab_mcp/tools/payee_patterns.py` (add these imports at the top alongside the existing ones):

```python
import statistics
from collections import Counter
```

Then add:

```python
_RECURRING_MIN_COUNT = 3
_RECURRING_TOLERANCE_FRACTION = 0.1
_RECURRING_TOLERANCE_FLOOR_MILLIUNITS = 1000


@dataclass(frozen=True)
class AmountRange:
    """The minimum and maximum transaction amount in a group, in milliunits.

    Parameters
    ----------
    min : int
        The smallest transaction amount.
    max : int
        The largest transaction amount.
    """

    min: int
    max: int


@dataclass(frozen=True)
class PayeeGroupSummary:
    """Transaction-pattern statistics for one matched payee.

    Parameters
    ----------
    payee_id : str
        The matched YNAB payee id.
    payee_name : str
        The matched YNAB payee name.
    match_type : MatchType
        How this payee matched the caller's query.
    match_score : float | None
        The ``difflib`` similarity ratio, set only when ``match_type`` is
        ``"fuzzy"``.
    transaction_count : int
        Number of transactions for this payee.
    typical_amount : int
        Median transaction amount, in milliunits.
    amount_range : AmountRange
        The min/max transaction amount, in milliunits.
    most_common_category : str | None
        The mode of ``category_name`` across the group's transactions, or
        ``None`` if none are categorized.
    recurring_guess : str | None
        A human-readable recurring-charge guess when the heuristic fires,
        otherwise ``None``.
    """

    payee_id: str
    payee_name: str
    match_type: MatchType
    match_score: float | None
    transaction_count: int
    typical_amount: int
    amount_range: AmountRange
    most_common_category: str | None
    recurring_guess: str | None


def _most_common_category(transactions: list[ynab.TransactionDetail]) -> str | None:
    """Find the most frequent category name among a group's transactions.

    Parameters
    ----------
    transactions : list[ynab.TransactionDetail]
        The matched payee's transactions.

    Returns
    -------
    str | None
        The most common ``category_name``, or ``None`` if no transaction
        has a category.
    """
    categories = [t.category_name for t in transactions if t.category_name]
    if not categories:
        return None
    return Counter(categories).most_common(1)[0][0]


def _recurring_guess(amounts: list[int], typical_amount: int) -> str | None:
    """Guess whether a group of amounts represents a recurring charge.

    Fires when there are at least ``_RECURRING_MIN_COUNT`` transactions
    and every amount falls within a tolerance band of the median -- the
    greater of ``_RECURRING_TOLERANCE_FRACTION`` of the median or
    ``_RECURRING_TOLERANCE_FLOOR_MILLIUNITS``, so cheap recurring charges
    aren't missed by a purely percentage-based tolerance.

    Parameters
    ----------
    amounts : list[int]
        Every transaction amount in the group, in milliunits.
    typical_amount : int
        The group's median amount, in milliunits.

    Returns
    -------
    str | None
        A human-readable guess, or ``None`` if the heuristic doesn't fire.
    """
    if len(amounts) < _RECURRING_MIN_COUNT:
        return None
    tolerance = max(
        abs(typical_amount) * _RECURRING_TOLERANCE_FRACTION,
        _RECURRING_TOLERANCE_FLOOR_MILLIUNITS,
    )
    if not all(abs(amount - typical_amount) <= tolerance for amount in amounts):
        return None
    dollars = abs(typical_amount) / 1000
    return f"Looks like a recurring charge (~${dollars:.2f}, seen {len(amounts)} times)"


def _summarize_group(
    matched: _MatchedPayee, transactions: list[ynab.TransactionDetail]
) -> PayeeGroupSummary:
    """Compute transaction-pattern statistics for one matched payee.

    Parameters
    ----------
    matched : _MatchedPayee
        The payee this group belongs to, and how it matched.
    transactions : list[ynab.TransactionDetail]
        The matched payee's transactions. Must be non-empty.

    Returns
    -------
    PayeeGroupSummary
        The computed statistics for this payee's transactions.
    """
    amounts = [t.amount for t in transactions]
    typical_amount = round(statistics.median(amounts))
    return PayeeGroupSummary(
        payee_id=str(matched.payee.id),
        payee_name=matched.payee.name,
        match_type=matched.match_type,
        match_score=matched.match_score,
        transaction_count=len(transactions),
        typical_amount=typical_amount,
        amount_range=AmountRange(min=min(amounts), max=max(amounts)),
        most_common_category=_most_common_category(transactions),
        recurring_guess=_recurring_guess(amounts, typical_amount),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_payee_patterns.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/tools/payee_patterns.py tests/test_tools_payee_patterns.py
git commit -m "feat: add transaction-stats aggregation for find-payee-transactions"
git push
```

---

### Task 3: Public orchestrating function

**Files:**
- Modify: `src/ynab_mcp/tools/payee_patterns.py`
- Test: `tests/test_tools_payee_patterns.py`

**Interfaces:**
- Consumes: `_match_payees` (Task 1), `_summarize_group` (Task 2), `PayeeGroupSummary` (Task 2), `list_payees(client, budget_id) -> list[ynab.Payee]` (`ynab_mcp.tools.payees`), `list_transactions(client, budget_id, payee_id=...) -> list[ynab.TransactionDetail]` (`ynab_mcp.tools.transactions`).
- Produces: `find_payee_transactions(client: ynab.ApiClient, budget_id: str, payee_query: str, fuzzy_threshold: float = 0.6) -> list[PayeeGroupSummary]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tools_payee_patterns.py`:

```python
from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

from ynab_mcp.tools.payee_patterns import find_payee_transactions


def test_find_payee_transactions_returns_summary_for_matched_payee(
    mocker: MockerFixture,
) -> None:
    """A matching payee with transactions produces one summary."""
    client = mocker.Mock()
    list_payees_mock = mocker.patch("ynab_mcp.tools.payee_patterns.list_payees")
    list_payees_mock.return_value = [SimpleNamespace(id="p1", name="Amazon.com")]
    list_transactions_mock = mocker.patch(
        "ynab_mcp.tools.payee_patterns.list_transactions"
    )
    list_transactions_mock.return_value = [
        _transaction(-5000, "Shopping"),
        _transaction(-5000, "Shopping"),
        _transaction(-5000, "Shopping"),
    ]

    result = find_payee_transactions(client, "budget-1", "amazon")

    assert len(result) == 1
    assert result[0].payee_id == "p1"
    assert result[0].transaction_count == 3
    list_payees_mock.assert_called_once_with(client, "budget-1")
    list_transactions_mock.assert_called_once_with(
        client, "budget-1", payee_id="p1"
    )


def test_find_payee_transactions_no_match_returns_empty_list(
    mocker: MockerFixture,
) -> None:
    """No matching payee produces an empty result, not an error."""
    client = mocker.Mock()
    list_payees_mock = mocker.patch("ynab_mcp.tools.payee_patterns.list_payees")
    list_payees_mock.return_value = [SimpleNamespace(id="p1", name="Netflix")]
    list_transactions_mock = mocker.patch(
        "ynab_mcp.tools.payee_patterns.list_transactions"
    )

    result = find_payee_transactions(client, "budget-1", "walmart")

    assert result == []
    list_transactions_mock.assert_not_called()


def test_find_payee_transactions_excludes_payee_with_no_transactions(
    mocker: MockerFixture,
) -> None:
    """A matched payee with zero transactions is excluded from the result."""
    client = mocker.Mock()
    list_payees_mock = mocker.patch("ynab_mcp.tools.payee_patterns.list_payees")
    list_payees_mock.return_value = [SimpleNamespace(id="p1", name="Amazon.com")]
    list_transactions_mock = mocker.patch(
        "ynab_mcp.tools.payee_patterns.list_transactions"
    )
    list_transactions_mock.return_value = []

    result = find_payee_transactions(client, "budget-1", "amazon")

    assert result == []


def test_find_payee_transactions_rejects_empty_query(
    mocker: MockerFixture,
) -> None:
    """An empty or whitespace-only payee_query raises ToolError."""
    client = mocker.Mock()

    with raises(ToolError, match="payee_query"):
        find_payee_transactions(client, "budget-1", "   ")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_payee_patterns.py -v`
Expected: FAIL with `ImportError: cannot import name 'find_payee_transactions'`

- [ ] **Step 3: Write the minimal implementation**

Append to `src/ynab_mcp/tools/payee_patterns.py` (add these imports at the top alongside the existing ones):

```python
from fastmcp.exceptions import ToolError

from ynab_mcp.tools.payees import list_payees
from ynab_mcp.tools.transactions import list_transactions
```

Then add:

```python
def find_payee_transactions(
    client: ynab.ApiClient,
    budget_id: str,
    payee_query: str,
    fuzzy_threshold: float = 0.6,
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

    summaries: list[PayeeGroupSummary] = []
    for matched in matches:
        transactions = list_transactions(
            client, budget_id, payee_id=str(matched.payee.id)
        )
        if not transactions:
            continue
        summaries.append(_summarize_group(matched, transactions))
    return summaries
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_payee_patterns.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/tools/payee_patterns.py tests/test_tools_payee_patterns.py
git commit -m "feat: add find_payee_transactions orchestrating function"
git push
```

---

### Task 4: MCP tool registration and server wiring

**Files:**
- Modify: `src/ynab_mcp/tools/payee_patterns.py`
- Modify: `src/ynab_mcp/server.py`
- Modify: `tests/test_server.py`
- Modify: `tests/test_e2e_server.py`

**Interfaces:**
- Consumes: `find_payee_transactions` (Task 3), `resolve_budget_id` (`ynab_mcp.client`), `Settings` (`ynab_mcp.config`).
- Produces: `register(mcp: FastMCP, client: ynab.ApiClient, settings: Settings) -> None`, registering the `find-payee-transactions` MCP tool.

- [ ] **Step 1: Write the failing test**

Modify `tests/test_server.py`'s `test_build_server_registers_all_other_tools` to include the new tool name:

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
        "find-payee-transactions",
    }
```

Also update `tests/test_e2e_server.py`'s expected tool set:

```python
    assert tool_names == {
        "list-budgets",
        "list-accounts",
        "list-categories",
        "list-transactions",
        "get-month-info",
        "list-payees",
        "lookup-entity-by-id",
        "find-payee-transactions",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_server.py -v`
Expected: FAIL — `test_build_server_registers_all_other_tools` asserts a set missing `"find-payee-transactions"` from the actual registered tools (`AssertionError` on set equality).

- [ ] **Step 3: Write the minimal implementation**

Change the existing `from dataclasses import dataclass` line (added in Task 1) to also import `asdict`:

```python
from dataclasses import asdict, dataclass
```

Add these new imports at the top alongside the existing ones:

```python
from fastmcp import FastMCP

from ynab_mcp.client import resolve_budget_id
from ynab_mcp.config import Settings
```

Then add:

```python
def register(mcp: FastMCP, client: ynab.ApiClient, settings: Settings) -> None:
    """Register the ``find-payee-transactions`` tool on ``mcp``.

    Parameters
    ----------
    mcp : fastmcp.FastMCP
        The server to register the tool on.
    client : ynab.ApiClient
        A configured YNAB API client.
    settings : Settings
        The server's parsed configuration, used to resolve a default
        budget id when the caller omits one.
    """

    @mcp.tool(name="find-payee-transactions")
    def find_payee_transactions_tool(
        payee_query: str, budget_id: str | None = None
    ) -> list[dict[str, object]]:
        """Find transaction patterns for payees matching a query.

        Parameters
        ----------
        payee_query : str
            A payee name or substring to search for.
        budget_id : str | None, optional
            The YNAB budget id, by default ``None`` (falls back to
            ``YNAB_DEFAULT_BUDGET_ID``).
        """
        resolved_budget_id = resolve_budget_id(budget_id, settings)
        summaries = find_payee_transactions(client, resolved_budget_id, payee_query)
        return [asdict(summary) for summary in summaries]
```

Modify `src/ynab_mcp/server.py` -- add `payee_patterns` to the import block and register it:

```python
from ynab_mcp.tools import (
    accounts,
    budgets,
    categories,
    lookup,
    months,
    payee_patterns,
    payees,
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
    payee_patterns.register(mcp, client, settings)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_server.py -v`
Expected: PASS (4 tests)

Run: `make e2e`
Expected: PASS (1 test) -- confirms the real `uv run ynab-mcp` stdio server lists `find-payee-transactions` too.

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/tools/payee_patterns.py src/ynab_mcp/server.py tests/test_server.py tests/test_e2e_server.py
git commit -m "feat: register find-payee-transactions tool on the server"
git push
```

---

### Task 5: Full verification pass

**Files:** None (verification only).

**Interfaces:** None.

- [ ] **Step 1: Run the full unit test suite**

Run: `make tests`
Expected: PASS, `59 passed` (46 existing + 13 new from Task 3, which supersede the earlier per-task counts in Tasks 1-2 since they're cumulative in the same file).

- [ ] **Step 2: Run lint**

Run: `make lint`
Expected: PASS -- `black --check`, `ruff check`, and `mypy` all clean on `src/ynab_mcp/tools/payee_patterns.py` and the modified `server.py`/test files.

- [ ] **Step 3: Run E2E**

Run: `make e2e`
Expected: PASS -- the real stdio server lists all 8 tools including `find-payee-transactions`.

- [ ] **Step 4: Fix any failures**

If `make lint` reports formatting issues, run `make format` and re-run `make lint`. If `mypy` reports type errors, fix the annotations in `payee_patterns.py` directly (e.g. missing return types on helpers) and re-run. Do not suppress errors with `# type: ignore` or `# noqa` -- fix the underlying issue.

- [ ] **Step 5: Commit if fixes were needed**

```bash
git add -u
git commit -m "fix: address lint/type findings in payee_patterns"
git push
```

If no fixes were needed, skip this step -- there's nothing to commit.
