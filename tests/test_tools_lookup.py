"""Tests for ynab_mcp.tools.lookup."""

from datetime import date
from types import SimpleNamespace

import tenacity
import ynab
from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

from ynab_mcp.tools.lookup import lookup_entity_by_id


def test_lookup_account_calls_get_account_by_id(mocker: MockerFixture) -> None:
    """entity_type='account' dispatches to AccountsApi.get_account_by_id."""
    client = mocker.Mock()
    accounts_api = mocker.patch("ynab_mcp.tools.lookup.ynab.AccountsApi")
    fake_account = SimpleNamespace(id="a1", name="Checking")
    accounts_api.return_value.get_account_by_id.return_value = SimpleNamespace(
        data=SimpleNamespace(account=fake_account)
    )

    result = lookup_entity_by_id(client, "budget-1", "account", "a1")

    assert result == fake_account
    accounts_api.return_value.get_account_by_id.assert_called_once_with(
        plan_id="budget-1", account_id="a1"
    )


def test_lookup_category_calls_get_category_by_id(mocker: MockerFixture) -> None:
    """entity_type='category' dispatches to CategoriesApi.get_category_by_id."""
    client = mocker.Mock()
    categories_api = mocker.patch("ynab_mcp.tools.lookup.ynab.CategoriesApi")
    fake_category = SimpleNamespace(id="c1", name="Groceries")
    categories_api.return_value.get_category_by_id.return_value = SimpleNamespace(
        data=SimpleNamespace(category=fake_category)
    )

    result = lookup_entity_by_id(client, "budget-1", "category", "c1")

    assert result == fake_category
    categories_api.return_value.get_category_by_id.assert_called_once_with(
        plan_id="budget-1", category_id="c1"
    )


def test_lookup_payee_calls_get_payee_by_id(mocker: MockerFixture) -> None:
    """entity_type='payee' dispatches to PayeesApi.get_payee_by_id."""
    client = mocker.Mock()
    payees_api = mocker.patch("ynab_mcp.tools.lookup.ynab.PayeesApi")
    fake_payee = SimpleNamespace(id="p1", name="Amazon")
    payees_api.return_value.get_payee_by_id.return_value = SimpleNamespace(
        data=SimpleNamespace(payee=fake_payee)
    )

    result = lookup_entity_by_id(client, "budget-1", "payee", "p1")

    assert result == fake_payee
    payees_api.return_value.get_payee_by_id.assert_called_once_with(
        plan_id="budget-1", payee_id="p1"
    )


def test_lookup_transaction_calls_get_transaction_by_id(
    mocker: MockerFixture,
) -> None:
    """entity_type='transaction' dispatches to TransactionsApi.get_transaction_by_id."""
    client = mocker.Mock()
    transactions_api = mocker.patch("ynab_mcp.tools.lookup.ynab.TransactionsApi")
    fake_transaction = SimpleNamespace(id="t1")
    transactions_api.return_value.get_transaction_by_id.return_value = SimpleNamespace(
        data=SimpleNamespace(transaction=fake_transaction)
    )

    result = lookup_entity_by_id(client, "budget-1", "transaction", "t1")

    assert result == fake_transaction
    transactions_api.return_value.get_transaction_by_id.assert_called_once_with(
        plan_id="budget-1", transaction_id="t1"
    )


def test_lookup_month_calls_get_plan_month(mocker: MockerFixture) -> None:
    """entity_type='month' parses entity_id and dispatches to get_plan_month."""
    client = mocker.Mock()
    months_api = mocker.patch("ynab_mcp.tools.lookup.ynab.MonthsApi")
    fake_month = SimpleNamespace(month=date(2024, 3, 1))
    months_api.return_value.get_plan_month.return_value = SimpleNamespace(
        data=SimpleNamespace(month=fake_month)
    )

    result = lookup_entity_by_id(client, "budget-1", "month", "2024-03-01")

    assert result == fake_month
    months_api.return_value.get_plan_month.assert_called_once_with(
        plan_id="budget-1", month=date(2024, 3, 1)
    )


def test_lookup_rejects_unknown_entity_type(mocker: MockerFixture) -> None:
    """An entity_type outside the known set raises a ToolError."""
    client = mocker.Mock()

    with raises(ToolError, match="Unknown entity_type"):
        lookup_entity_by_id(client, "budget-1", "invoice", "x1")  # type: ignore[arg-type]


def test_lookup_raises_tool_error_on_api_exception(mocker: MockerFixture) -> None:
    """An ApiException from the SDK surfaces as a ToolError."""
    client = mocker.Mock()
    accounts_api = mocker.patch("ynab_mcp.tools.lookup.ynab.AccountsApi")
    accounts_api.return_value.get_account_by_id.side_effect = ynab.ApiException(
        status=404,
        reason="Not Found",
        body='{"error": {"id": "404", "name": "not_found", '
        '"detail": "Account not found"}}',
    )

    with raises(ToolError, match="Account not found"):
        lookup_entity_by_id(client, "budget-1", "account", "missing")


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
