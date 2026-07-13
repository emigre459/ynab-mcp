"""Tests for ynab_mcp.tools.spend_analysis."""

from datetime import date
from types import SimpleNamespace

import ynab
from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

from ynab_mcp.tools.spend_analysis import (
    _direction,
    _fetch_month_categories,
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
    assert _spent_milli(category) == 420000  # type: ignore[arg-type]


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
        data=SimpleNamespace(
            month=SimpleNamespace(categories=[visible, hidden, deleted])
        )
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
