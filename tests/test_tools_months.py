"""Tests for ynab_mcp.tools.months."""

from datetime import date
from types import SimpleNamespace

import tenacity
import ynab
from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

from ynab_mcp.tools.months import get_month_info, parse_month


def test_parse_month_accepts_iso_date() -> None:
    """An ISO date string parses to the matching date."""
    assert parse_month("2024-03-01") == date(2024, 3, 1)


def test_parse_month_accepts_current() -> None:
    """The literal 'current' resolves to the first of this month."""
    result = parse_month("current")

    assert result == date.today().replace(day=1)


def test_parse_month_rejects_invalid_value() -> None:
    """An unparseable month string raises a ToolError with a hint."""
    with raises(ToolError, match="Invalid month"):
        parse_month("not-a-date")


def test_get_month_info_returns_month_detail(mocker: MockerFixture) -> None:
    """get_month_info calls MonthsApi.get_plan_month with the parsed month."""
    client = mocker.Mock()
    months_api = mocker.patch("ynab_mcp.tools.months.ynab.MonthsApi")
    fake_month = SimpleNamespace(month=date(2024, 3, 1), budgeted=100000)
    months_api.return_value.get_plan_month.return_value = SimpleNamespace(
        data=SimpleNamespace(month=fake_month)
    )

    result = get_month_info(client, "budget-1", "2024-03-01")

    assert result == fake_month
    months_api.return_value.get_plan_month.assert_called_once_with(
        plan_id="budget-1", month=date(2024, 3, 1)
    )


def test_get_month_info_raises_tool_error_on_api_exception(
    mocker: MockerFixture,
) -> None:
    """An ApiException from the SDK surfaces as a ToolError."""
    client = mocker.Mock()
    months_api = mocker.patch("ynab_mcp.tools.months.ynab.MonthsApi")
    months_api.return_value.get_plan_month.side_effect = ynab.ApiException(
        status=404,
        reason="Not Found",
        body='{"error": {"id": "404", "name": "not_found", '
        '"detail": "Budget not found"}}',
    )

    with raises(ToolError, match="Budget not found"):
        get_month_info(client, "missing-budget", "2024-03-01")


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
