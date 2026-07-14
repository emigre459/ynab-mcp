"""Tests for ynab_mcp.tools.spend_analysis."""

from datetime import date
from types import SimpleNamespace

import ynab
from fastmcp.exceptions import ToolError
from pytest import approx, raises
from pytest_mock import MockerFixture

from ynab_mcp.tools.spend_analysis import (
    _direction,
    _fetch_month_categories,
    _percent_diff,
    _spent_milli,
    _to_dollars,
    _trailing_months,
    analyze_category_trends,
    flag_category_spend,
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


def test_direction_zero_threshold_exact_match_is_none() -> None:
    """Spend exactly equal to budget is never flagged, even at threshold=0."""
    assert _direction(300000, 300000, 0.0) is None


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
    assert "420.00" in flag["reason"]  # type: ignore[operator]
    assert "300.00" in flag["reason"]  # type: ignore[operator]
    assert "40%" in flag["reason"]  # type: ignore[operator]
    assert "over" in flag["reason"]  # type: ignore[operator]


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
    assert "no budget allocated" in result[0]["reason"]  # type: ignore[operator]


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
    monthly = [[_category(budgeted=b, activity=a)] for b, a in zip(budgets, activities)]
    _mock_month_sequence(mocker, monthly)

    result = analyze_category_trends(
        client, "budget-1", months=6, end_month="2024-06-01"
    )

    assert len(result) == 1
    flag = result[0]
    assert flag["trend"] == "rising_overspend"
    assert flag["category_id"] == "cat-1"
    assert flag["budgeted"] == 350.00
    assert flag["months_over_threshold"] >= 3  # type: ignore[operator]
    assert flag["months_in_window"] == 6
    assert "rising_overspend" not in flag["reason"]  # type: ignore[operator]
    assert "overspent" in flag["reason"]  # type: ignore[operator]


def test_analyze_category_trends_detects_persistent_underspend(
    mocker: MockerFixture,
) -> None:
    """A category consistently underspent is flagged, regardless of budget trend."""
    client = mocker.Mock()
    monthly = [[_category(budgeted=300000, activity=-50000)] for _ in range(6)]
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
    monthly = [[_category(budgeted=300000, activity=a)] for a in activities]
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
    assert "2/6" in flag["reason"]  # type: ignore[operator]


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
    """Months < 1 raises a ToolError."""
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
        analyze_category_trends(
            client, "missing-budget", months=6, end_month="2024-06-01"
        )
