"""Tests for ynab_mcp.tools.payee_patterns."""

from types import SimpleNamespace

from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

from ynab_mcp.tools.payee_patterns import (
    _MatchedPayee,
    _match_payees,
    _summarize_group,
    find_payee_transactions,
)


def test_match_payees_exact_match() -> None:
    """A payee name equal to the query (case-insensitive) matches exactly."""
    payees = [
        SimpleNamespace(id="p1", name="Amazon.com"),
        SimpleNamespace(id="p2", name="Starbucks"),
    ]

    matches = _match_payees(payees, "amazon.com", fuzzy_threshold=0.6)  # type: ignore[arg-type]

    assert len(matches) == 1
    assert matches[0].payee.id == "p1"
    assert matches[0].match_type == "exact"
    assert matches[0].match_score is None


def test_match_payees_substring_match() -> None:
    """A query that is a substring of the payee name matches by substring."""
    payees = [SimpleNamespace(id="p1", name="AMZN Mktp US Amazon")]

    matches = _match_payees(payees, "amazon", fuzzy_threshold=0.6)  # type: ignore[arg-type]

    assert len(matches) == 1
    assert matches[0].match_type == "substring"
    assert matches[0].match_score is None


def test_match_payees_fuzzy_match() -> None:
    """A payee name that doesn't literally contain the query still matches.

    It matches by fuzzy similarity when its score is above the threshold.
    """
    payees = [SimpleNamespace(id="p1", name="Wal-Mart #1234")]

    matches = _match_payees(payees, "walmart", fuzzy_threshold=0.6)  # type: ignore[arg-type]

    assert len(matches) == 1
    assert matches[0].match_type == "fuzzy"
    assert matches[0].match_score is not None
    assert matches[0].match_score >= 0.6


def test_match_payees_no_match() -> None:
    """A payee name that doesn't match at all is excluded entirely.

    It scores below the fuzzy threshold and doesn't contain the query.
    """
    payees = [SimpleNamespace(id="p1", name="Netflix")]

    matches = _match_payees(payees, "walmart", fuzzy_threshold=0.6)  # type: ignore[arg-type]

    assert matches == []


def _transaction(
    amount: int,
    category_name: str | None,
    subtransactions: list[SimpleNamespace] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        amount=amount,
        category_name=category_name,
        subtransactions=subtransactions or [],
    )


def _subtransaction(category_name: str | None) -> SimpleNamespace:
    return SimpleNamespace(category_name=category_name)


def test_summarize_group_computes_stats() -> None:
    """Transaction count, typical amount, amount range, and most common category.

    Computed correctly from a matched payee's transactions.
    """
    matched = _MatchedPayee(
        payee=SimpleNamespace(id="p1", name="Coffee Shop"),  # type: ignore[arg-type]
        match_type="exact",
        match_score=None,
    )
    transactions = [
        _transaction(-5000, "Dining Out"),
        _transaction(-5500, "Dining Out"),
        _transaction(-4500, "Groceries"),
    ]

    summary = _summarize_group(matched, transactions)  # type: ignore[arg-type]

    assert summary.payee_id == "p1"
    assert summary.payee_name == "Coffee Shop"
    assert summary.match_type == "exact"
    assert summary.transaction_count == 3
    assert summary.typical_amount == -5000
    assert summary.amount_range.min == -5500
    assert summary.amount_range.max == -4500
    assert summary.most_common_category == "Dining Out"


def test_summarize_group_uses_subtransaction_categories_for_split_transactions() -> (
    None
):
    """A split transaction's own "Split" category_name is never counted.

    Its subtransactions' real categories are counted instead.
    """
    matched = _MatchedPayee(
        payee=SimpleNamespace(id="p1", name="Costco"),  # type: ignore[arg-type]
        match_type="exact",
        match_score=None,
    )
    transactions = [
        _transaction(
            -10000,
            "Split",
            subtransactions=[
                _subtransaction("Groceries"),
                _subtransaction("Groceries"),
            ],
        ),
        _transaction(-3000, "Dining Out"),
    ]

    summary = _summarize_group(matched, transactions)  # type: ignore[arg-type]

    assert summary.most_common_category == "Groceries"


def test_summarize_group_no_common_category_when_uncategorized() -> None:
    """most_common_category is None when no transaction has a category."""
    matched = _MatchedPayee(
        payee=SimpleNamespace(id="p1", name="Coffee Shop"),  # type: ignore[arg-type]
        match_type="exact",
        match_score=None,
    )
    transactions = [_transaction(-5000, None), _transaction(-5000, None)]

    summary = _summarize_group(matched, transactions)  # type: ignore[arg-type]

    assert summary.most_common_category is None


def test_summarize_group_recurring_guess_fires() -> None:
    """recurring_guess is set when >=3 transactions have consistent amounts.

    Tests that the heuristic fires.
    """
    matched = _MatchedPayee(
        payee=SimpleNamespace(id="p1", name="Streaming Service"),  # type: ignore[arg-type]
        match_type="exact",
        match_score=None,
    )
    transactions = [
        _transaction(-14990, "Entertainment"),
        _transaction(-14990, "Entertainment"),
        _transaction(-14990, "Entertainment"),
    ]

    summary = _summarize_group(matched, transactions)  # type: ignore[arg-type]

    assert summary.recurring_guess is not None
    assert "14.99" in summary.recurring_guess
    assert "3" in summary.recurring_guess


def test_summarize_group_recurring_guess_does_not_fire_below_count() -> None:
    """recurring_guess is None with fewer than 3 transactions.

    Even if amounts are consistent.
    """
    matched = _MatchedPayee(
        payee=SimpleNamespace(id="p1", name="Streaming Service"),  # type: ignore[arg-type]
        match_type="exact",
        match_score=None,
    )
    transactions = [_transaction(-14990, None), _transaction(-14990, None)]

    summary = _summarize_group(matched, transactions)  # type: ignore[arg-type]

    assert summary.recurring_guess is None


def test_summarize_group_recurring_guess_does_not_fire_inconsistent_amounts() -> None:
    """recurring_guess is None when amounts vary too much.

    Even with enough transactions.
    """
    matched = _MatchedPayee(
        payee=SimpleNamespace(id="p1", name="Grocery Store"),  # type: ignore[arg-type]
        match_type="exact",
        match_score=None,
    )
    transactions = [
        _transaction(-2000, None),
        _transaction(-9000, None),
        _transaction(-15000, None),
    ]

    summary = _summarize_group(matched, transactions)  # type: ignore[arg-type]

    assert summary.recurring_guess is None


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
    list_transactions_mock.assert_called_once_with(client, "budget-1", payee_id="p1")


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
    transactions_by_payee = {
        "p1": [_transaction(-5000, "Shopping")],
        "p2": [_transaction(-3000, "Shopping"), _transaction(-3200, "Shopping")],
    }
    list_transactions_mock = mocker.patch(
        "ynab_mcp.tools.payee_patterns.list_transactions"
    )
    list_transactions_mock.side_effect = (
        lambda client, budget_id, payee_id: transactions_by_payee[payee_id]
    )

    result = find_payee_transactions(client, "budget-1", "amazon")

    assert len(result) == 2
    assert result[0].payee_id == "p1"
    assert result[0].transaction_count == 1
    assert result[1].payee_id == "p2"
    assert result[1].transaction_count == 2


def test_find_payee_transactions_rejects_empty_query(
    mocker: MockerFixture,
) -> None:
    """An empty or whitespace-only payee_query raises ToolError."""
    client = mocker.Mock()

    with raises(ToolError, match="payee_query"):
        find_payee_transactions(client, "budget-1", "   ")
