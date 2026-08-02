"""Tests for ynab_mcp.tools.accounts."""

from types import SimpleNamespace

import tenacity
import ynab
from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

from ynab_mcp.tools.accounts import list_accounts


def test_list_accounts_returns_accounts_for_budget(mocker: MockerFixture) -> None:
    """list_accounts calls AccountsApi.get_accounts with plan_id=budget_id."""
    client = mocker.Mock()
    accounts_api = mocker.patch("ynab_mcp.tools.accounts.ynab.AccountsApi")
    fake_accounts = [SimpleNamespace(id="a1", name="Checking")]
    accounts_api.return_value.get_accounts.return_value = SimpleNamespace(
        data=SimpleNamespace(accounts=fake_accounts)
    )

    result = list_accounts(client, "budget-1")

    assert result == fake_accounts
    accounts_api.return_value.get_accounts.assert_called_once_with(plan_id="budget-1")


def test_list_accounts_raises_tool_error_on_api_exception(
    mocker: MockerFixture,
) -> None:
    """An ApiException from the SDK surfaces as a ToolError."""
    client = mocker.Mock()
    accounts_api = mocker.patch("ynab_mcp.tools.accounts.ynab.AccountsApi")
    accounts_api.return_value.get_accounts.side_effect = ynab.ApiException(
        status=404,
        reason="Not Found",
        body='{"error": {"id": "404", "name": "not_found", '
        '"detail": "Budget not found"}}',
    )

    with raises(ToolError, match="Budget not found"):
        list_accounts(client, "missing-budget")


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
