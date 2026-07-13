"""Tests for ynab_mcp.tools.transactions."""

from datetime import date
from types import SimpleNamespace

import ynab
from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

from ynab_mcp.tools.transactions import list_transactions


def test_list_transactions_with_no_filters_calls_get_transactions(
    mocker: MockerFixture,
) -> None:
    """No entity filter dispatches to the plain get_transactions endpoint."""
    client = mocker.Mock()
    transactions_api = mocker.patch("ynab_mcp.tools.transactions.ynab.TransactionsApi")
    fake_transactions = [SimpleNamespace(id="t1")]
    transactions_api.return_value.get_transactions.return_value = SimpleNamespace(
        data=SimpleNamespace(transactions=fake_transactions)
    )

    result = list_transactions(client, "budget-1")

    assert result == fake_transactions
    transactions_api.return_value.get_transactions.assert_called_once_with(
        plan_id="budget-1", since_date=None, until_date=None
    )


def test_list_transactions_with_account_id_calls_get_transactions_by_account(
    mocker: MockerFixture,
) -> None:
    """account_id dispatches to get_transactions_by_account."""
    client = mocker.Mock()
    transactions_api = mocker.patch("ynab_mcp.tools.transactions.ynab.TransactionsApi")
    fake_transactions = [SimpleNamespace(id="t1")]
    transactions_api.return_value.get_transactions_by_account.return_value = (
        SimpleNamespace(data=SimpleNamespace(transactions=fake_transactions))
    )

    result = list_transactions(
        client,
        "budget-1",
        account_id="acct-1",
        since_date=date(2024, 1, 1),
        until_date=date(2024, 2, 1),
    )

    assert result == fake_transactions
    transactions_api.return_value.get_transactions_by_account.assert_called_once_with(
        plan_id="budget-1",
        account_id="acct-1",
        since_date=date(2024, 1, 1),
        until_date=date(2024, 2, 1),
    )


def test_list_transactions_with_category_id_calls_get_transactions_by_category(
    mocker: MockerFixture,
) -> None:
    """category_id dispatches to get_transactions_by_category."""
    client = mocker.Mock()
    transactions_api = mocker.patch("ynab_mcp.tools.transactions.ynab.TransactionsApi")
    fake_transactions = [SimpleNamespace(id="t1")]
    transactions_api.return_value.get_transactions_by_category.return_value = (
        SimpleNamespace(data=SimpleNamespace(transactions=fake_transactions))
    )

    result = list_transactions(client, "budget-1", category_id="cat-1")

    assert result == fake_transactions
    transactions_api.return_value.get_transactions_by_category.assert_called_once_with(
        plan_id="budget-1", category_id="cat-1", since_date=None, until_date=None
    )


def test_list_transactions_with_payee_id_calls_get_transactions_by_payee(
    mocker: MockerFixture,
) -> None:
    """payee_id dispatches to get_transactions_by_payee."""
    client = mocker.Mock()
    transactions_api = mocker.patch("ynab_mcp.tools.transactions.ynab.TransactionsApi")
    fake_transactions = [SimpleNamespace(id="t1")]
    transactions_api.return_value.get_transactions_by_payee.return_value = (
        SimpleNamespace(data=SimpleNamespace(transactions=fake_transactions))
    )

    result = list_transactions(client, "budget-1", payee_id="payee-1")

    assert result == fake_transactions
    transactions_api.return_value.get_transactions_by_payee.assert_called_once_with(
        plan_id="budget-1", payee_id="payee-1", since_date=None, until_date=None
    )


def test_list_transactions_rejects_multiple_entity_filters(
    mocker: MockerFixture,
) -> None:
    """Passing more than one of account_id/category_id/payee_id is an error."""
    client = mocker.Mock()

    with raises(ToolError, match="at most one"):
        list_transactions(client, "budget-1", account_id="acct-1", category_id="cat-1")


def test_list_transactions_raises_tool_error_on_api_exception(
    mocker: MockerFixture,
) -> None:
    """An ApiException from the SDK surfaces as a ToolError."""
    client = mocker.Mock()
    transactions_api = mocker.patch("ynab_mcp.tools.transactions.ynab.TransactionsApi")
    transactions_api.return_value.get_transactions.side_effect = ynab.ApiException(
        status=404,
        reason="Not Found",
        body='{"error": {"id": "404", "name": "not_found", '
        '"detail": "Budget not found"}}',
    )

    with raises(ToolError, match="Budget not found"):
        list_transactions(client, "missing-budget")
