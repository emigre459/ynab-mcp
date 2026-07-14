"""Tests for ynab_mcp.tools.budgeted_amount."""

import asyncio
from types import SimpleNamespace

import ynab
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

from ynab_mcp.config import Settings
from ynab_mcp.tools import budgeted_amount
from ynab_mcp.tools.budgeted_amount import assign_budgeted_amount, move_budgeted_amount


def test_assign_budgeted_amount_calls_update_month_category(
    mocker: MockerFixture,
) -> None:
    """assign_budgeted_amount sets the category's budgeted amount for the month."""
    client = mocker.Mock()
    categories_api = mocker.patch("ynab_mcp.tools.budgeted_amount.ynab.CategoriesApi")
    fake_category = SimpleNamespace(id="cat-1", budgeted=50000)
    categories_api.return_value.update_month_category.return_value = SimpleNamespace(
        data=SimpleNamespace(category=fake_category)
    )

    result = assign_budgeted_amount(client, "budget-1", "current", "cat-1", 50000)

    assert result == fake_category
    call = categories_api.return_value.update_month_category.call_args
    assert call.kwargs["plan_id"] == "budget-1"
    assert call.kwargs["category_id"] == "cat-1"
    assert call.kwargs["data"].category.budgeted == 50000


def test_assign_budgeted_amount_raises_tool_error_on_api_exception(
    mocker: MockerFixture,
) -> None:
    """An ApiException from the SDK surfaces as a ToolError."""
    client = mocker.Mock()
    categories_api = mocker.patch("ynab_mcp.tools.budgeted_amount.ynab.CategoriesApi")
    categories_api.return_value.update_month_category.side_effect = ynab.ApiException(
        status=404,
        reason="Not Found",
        body='{"error": {"id": "404", "name": "not_found", '
        '"detail": "Category not found"}}',
    )

    with raises(ToolError, match="Category not found"):
        assign_budgeted_amount(client, "budget-1", "current", "missing-cat", 50000)


def test_move_budgeted_amount_decrements_source_and_increments_target(
    mocker: MockerFixture,
) -> None:
    """move_budgeted_amount reads both categories then shifts the amount."""
    client = mocker.Mock()
    categories_api = mocker.patch("ynab_mcp.tools.budgeted_amount.ynab.CategoriesApi")
    categories_api.return_value.get_month_category_by_id.side_effect = [
        SimpleNamespace(
            data=SimpleNamespace(category=SimpleNamespace(budgeted=100000))
        ),
        SimpleNamespace(data=SimpleNamespace(category=SimpleNamespace(budgeted=20000))),
    ]
    updated_from = SimpleNamespace(id="from-cat", budgeted=80000)
    updated_to = SimpleNamespace(id="to-cat", budgeted=40000)
    categories_api.return_value.update_month_category.side_effect = [
        SimpleNamespace(data=SimpleNamespace(category=updated_from)),
        SimpleNamespace(data=SimpleNamespace(category=updated_to)),
    ]

    result = move_budgeted_amount(
        client, "budget-1", "current", "from-cat", "to-cat", 20000
    )

    assert result == {"from_category": updated_from, "to_category": updated_to}
    update_calls = categories_api.return_value.update_month_category.call_args_list
    assert update_calls[0].kwargs["category_id"] == "from-cat"
    assert update_calls[0].kwargs["data"].category.budgeted == 80000
    assert update_calls[1].kwargs["category_id"] == "to-cat"
    assert update_calls[1].kwargs["data"].category.budgeted == 40000


def test_move_budgeted_amount_rolls_back_source_on_target_failure(
    mocker: MockerFixture,
) -> None:
    """A failed target update restores the source's original amount and raises."""
    client = mocker.Mock()
    categories_api = mocker.patch("ynab_mcp.tools.budgeted_amount.ynab.CategoriesApi")
    categories_api.return_value.get_month_category_by_id.side_effect = [
        SimpleNamespace(
            data=SimpleNamespace(category=SimpleNamespace(budgeted=100000))
        ),
        SimpleNamespace(data=SimpleNamespace(category=SimpleNamespace(budgeted=20000))),
    ]
    updated_from = SimpleNamespace(id="from-cat", budgeted=80000)
    rollback_response = SimpleNamespace(
        data=SimpleNamespace(category=SimpleNamespace(id="from-cat", budgeted=100000))
    )
    categories_api.return_value.update_month_category.side_effect = [
        SimpleNamespace(data=SimpleNamespace(category=updated_from)),
        ynab.ApiException(
            status=404,
            reason="Not Found",
            body='{"error": {"id": "404", "name": "not_found", '
            '"detail": "Category not found"}}',
        ),
        rollback_response,
    ]

    with raises(ToolError, match="restored to its original budgeted amount"):
        move_budgeted_amount(
            client, "budget-1", "current", "from-cat", "missing-cat", 20000
        )

    update_calls = categories_api.return_value.update_month_category.call_args_list
    assert len(update_calls) == 3
    assert update_calls[2].kwargs["category_id"] == "from-cat"
    assert update_calls[2].kwargs["data"].category.budgeted == 100000


def test_move_budgeted_amount_reports_failed_rollback(mocker: MockerFixture) -> None:
    """If the rollback also fails, the error names the inconsistent state."""
    client = mocker.Mock()
    categories_api = mocker.patch("ynab_mcp.tools.budgeted_amount.ynab.CategoriesApi")
    categories_api.return_value.get_month_category_by_id.side_effect = [
        SimpleNamespace(
            data=SimpleNamespace(category=SimpleNamespace(budgeted=100000))
        ),
        SimpleNamespace(data=SimpleNamespace(category=SimpleNamespace(budgeted=20000))),
    ]
    updated_from = SimpleNamespace(id="from-cat", budgeted=80000)
    categories_api.return_value.update_month_category.side_effect = [
        SimpleNamespace(data=SimpleNamespace(category=updated_from)),
        ynab.ApiException(
            status=404,
            reason="Not Found",
            body='{"error": {"id": "404", "name": "not_found", '
            '"detail": "Category not found"}}',
        ),
        ynab.ApiException(
            status=500,
            reason="Server Error",
            body='{"error": {"id": "500", "name": "internal", '
            '"detail": "Service unavailable"}}',
        ),
    ]

    with raises(ToolError, match="Rollback of the source category also failed"):
        move_budgeted_amount(
            client, "budget-1", "current", "from-cat", "missing-cat", 20000
        )


def _build_registered_server(settings: Settings) -> FastMCP:
    """Build a minimal FastMCP server with only manage-budgeted-amount registered."""
    mcp = FastMCP("test")
    budgeted_amount.register(mcp, object(), settings)  # type: ignore[arg-type]
    return mcp


def test_manage_budgeted_amount_tool_dispatches_assign(mocker: MockerFixture) -> None:
    """The assign operation calls assign_budgeted_amount with the args."""
    settings = Settings(
        ynab_pat="x", ynab_default_budget_id="budget-1", ynab_read_only=False
    )
    mcp = _build_registered_server(settings)
    assign_mock = mocker.patch(
        "ynab_mcp.tools.budgeted_amount.assign_budgeted_amount",
        return_value=SimpleNamespace(
            model_dump=lambda mode="json": {"id": "cat-1", "budgeted": 50000}
        ),
    )

    async def _call() -> dict[str, object]:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "manage-budgeted-amount",
                {
                    "operation": "assign",
                    "month": "current",
                    "category_id": "cat-1",
                    "amount": 50000,
                },
            )
            return result.data

    result = asyncio.run(_call())

    assert result == {"id": "cat-1", "budgeted": 50000}
    assign_mock.assert_called_once_with(
        mocker.ANY, "budget-1", "current", "cat-1", 50000
    )


def test_manage_budgeted_amount_tool_dispatches_move(mocker: MockerFixture) -> None:
    """The move operation calls move_budgeted_amount with the args."""
    settings = Settings(
        ynab_pat="x", ynab_default_budget_id="budget-1", ynab_read_only=False
    )
    mcp = _build_registered_server(settings)
    move_mock = mocker.patch(
        "ynab_mcp.tools.budgeted_amount.move_budgeted_amount",
        return_value={
            "from_category": SimpleNamespace(
                model_dump=lambda mode="json": {"id": "from-cat", "budgeted": 80000}
            ),
            "to_category": SimpleNamespace(
                model_dump=lambda mode="json": {"id": "to-cat", "budgeted": 40000}
            ),
        },
    )

    async def _call() -> dict[str, object]:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "manage-budgeted-amount",
                {
                    "operation": "move",
                    "month": "current",
                    "from_category_id": "from-cat",
                    "to_category_id": "to-cat",
                    "amount": 20000,
                },
            )
            return result.data

    result = asyncio.run(_call())

    assert result == {
        "from_category": {"id": "from-cat", "budgeted": 80000},
        "to_category": {"id": "to-cat", "budgeted": 40000},
    }
    move_mock.assert_called_once_with(
        mocker.ANY, "budget-1", "current", "from-cat", "to-cat", 20000
    )


def test_manage_budgeted_amount_tool_rejects_assign_without_required_fields(
    mocker: MockerFixture,
) -> None:
    """Assign without category_id/amount raises before dispatch."""
    settings = Settings(
        ynab_pat="x", ynab_default_budget_id="budget-1", ynab_read_only=False
    )
    mcp = _build_registered_server(settings)
    assign_mock = mocker.patch("ynab_mcp.tools.budgeted_amount.assign_budgeted_amount")

    async def _call() -> None:
        async with Client(mcp) as client:
            await client.call_tool(
                "manage-budgeted-amount", {"operation": "assign", "month": "current"}
            )

    with raises(ToolError, match="assign requires category_id and amount"):
        asyncio.run(_call())
    assign_mock.assert_not_called()


def test_manage_budgeted_amount_tool_rejects_move_without_required_fields(
    mocker: MockerFixture,
) -> None:
    """Move without from_category_id/to_category_id/amount raises before dispatch."""
    settings = Settings(
        ynab_pat="x", ynab_default_budget_id="budget-1", ynab_read_only=False
    )
    mcp = _build_registered_server(settings)
    move_mock = mocker.patch("ynab_mcp.tools.budgeted_amount.move_budgeted_amount")

    async def _call() -> None:
        async with Client(mcp) as client:
            await client.call_tool(
                "manage-budgeted-amount", {"operation": "move", "month": "current"}
            )

    with raises(
        ToolError, match="move requires from_category_id, to_category_id, and amount"
    ):
        asyncio.run(_call())
    move_mock.assert_not_called()
