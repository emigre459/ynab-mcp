"""Tests for ynab_mcp.tools.categories."""

from types import SimpleNamespace

import ynab
from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

from ynab_mcp.tools.categories import list_categories


def test_list_categories_flattens_category_groups(mocker: MockerFixture) -> None:
    """Categories nested under category_groups are flattened into one list."""
    client = mocker.Mock()
    categories_api = mocker.patch("ynab_mcp.tools.categories.ynab.CategoriesApi")
    group_1_categories = [SimpleNamespace(id="c1", name="Groceries")]
    group_2_categories = [SimpleNamespace(id="c2", name="Rent")]
    categories_api.return_value.get_categories.return_value = SimpleNamespace(
        data=SimpleNamespace(
            category_groups=[
                SimpleNamespace(categories=group_1_categories),
                SimpleNamespace(categories=group_2_categories),
            ]
        )
    )

    result = list_categories(client, "budget-1")

    assert result == group_1_categories + group_2_categories
    categories_api.return_value.get_categories.assert_called_once_with(
        plan_id="budget-1"
    )


def test_list_categories_raises_tool_error_on_api_exception(
    mocker: MockerFixture,
) -> None:
    """An ApiException from the SDK surfaces as a ToolError."""
    client = mocker.Mock()
    categories_api = mocker.patch("ynab_mcp.tools.categories.ynab.CategoriesApi")
    categories_api.return_value.get_categories.side_effect = ynab.ApiException(
        status=404,
        reason="Not Found",
        body='{"error": {"id": "404", "name": "not_found", '
        '"detail": "Budget not found"}}',
    )

    with raises(ToolError, match="Budget not found"):
        list_categories(client, "missing-budget")
