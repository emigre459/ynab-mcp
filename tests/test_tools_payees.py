"""Tests for ynab_mcp.tools.payees."""

from types import SimpleNamespace

import tenacity
import ynab
from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

from ynab_mcp.tools.payees import list_payees


def test_list_payees_returns_payees_for_budget(mocker: MockerFixture) -> None:
    """list_payees calls PayeesApi.get_payees with plan_id=budget_id."""
    client = mocker.Mock()
    payees_api = mocker.patch("ynab_mcp.tools.payees.ynab.PayeesApi")
    fake_payees = [SimpleNamespace(id="p1", name="Amazon")]
    payees_api.return_value.get_payees.return_value = SimpleNamespace(
        data=SimpleNamespace(payees=fake_payees)
    )

    result = list_payees(client, "budget-1")

    assert result == fake_payees
    payees_api.return_value.get_payees.assert_called_once_with(plan_id="budget-1")


def test_list_payees_raises_tool_error_on_api_exception(
    mocker: MockerFixture,
) -> None:
    """An ApiException from the SDK surfaces as a ToolError."""
    client = mocker.Mock()
    payees_api = mocker.patch("ynab_mcp.tools.payees.ynab.PayeesApi")
    payees_api.return_value.get_payees.side_effect = ynab.ApiException(
        status=404,
        reason="Not Found",
        body='{"error": {"id": "404", "name": "not_found", '
        '"detail": "Budget not found"}}',
    )

    with raises(ToolError, match="Budget not found"):
        list_payees(client, "missing-budget")


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
