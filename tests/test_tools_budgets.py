"""Tests for ynab_mcp.tools.budgets."""

from types import SimpleNamespace

import tenacity
import ynab
from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

from ynab_mcp.tools.budgets import list_budgets


def test_list_budgets_returns_plans(mocker: MockerFixture) -> None:
    """list_budgets calls PlansApi.get_plans and returns the plan list."""
    client = mocker.Mock()
    plans_api = mocker.patch("ynab_mcp.tools.budgets.ynab.PlansApi")
    fake_plans = [SimpleNamespace(id="1", name="Family Budget")]
    plans_api.return_value.get_plans.return_value = SimpleNamespace(
        data=SimpleNamespace(plans=fake_plans)
    )

    result = list_budgets(client)

    assert result == fake_plans
    plans_api.assert_called_once_with(client)
    plans_api.return_value.get_plans.assert_called_once_with()


def test_list_budgets_raises_tool_error_on_api_exception(
    mocker: MockerFixture,
) -> None:
    """An ApiException from the SDK surfaces as a ToolError."""
    client = mocker.Mock()
    plans_api = mocker.patch("ynab_mcp.tools.budgets.ynab.PlansApi")
    plans_api.return_value.get_plans.side_effect = ynab.ApiException(
        status=401,
        reason="Unauthorized",
        body='{"error": {"id": "401", "name": "unauthorized", '
        '"detail": "Unauthorized"}}',
    )

    with raises(ToolError, match="Unauthorized"):
        list_budgets(client)


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
