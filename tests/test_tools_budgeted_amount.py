"""Tests for ynab_mcp.tools.budgeted_amount."""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
import tenacity
import ynab
from conftest import approve_handler, decline_handler
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


def test_move_budgeted_amount_rejects_same_category(mocker: MockerFixture) -> None:
    """Moving a category into itself is rejected before any API call.

    Without this guard, the category is read once, decremented, then
    re-incremented using the stale pre-move value -- net effect: the
    category's budgeted amount increases by `amount` instead of staying
    unchanged, silently corrupting the budget.
    """
    client = mocker.Mock()
    categories_api = mocker.patch("ynab_mcp.tools.budgeted_amount.ynab.CategoriesApi")

    with raises(ToolError, match="from_category_id and to_category_id must differ"):
        move_budgeted_amount(
            client, "budget-1", "current", "same-cat", "same-cat", 20000
        )

    categories_api.return_value.get_month_category_by_id.assert_not_called()
    categories_api.return_value.update_month_category.assert_not_called()


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
    """If the rollback also fails, the error names the inconsistent state.

    The rollback's 500 is retryable (``include_5xx=True`` is the default),
    so it must persist across all retry attempts -- not just the first --
    for the rollback to actually exhaust retries and surface as a failure.
    ``_wait`` is stubbed out so those retries don't sleep in real time.
    """
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    client = mocker.Mock()
    categories_api = mocker.patch("ynab_mcp.tools.budgeted_amount.ynab.CategoriesApi")
    categories_api.return_value.get_month_category_by_id.side_effect = [
        SimpleNamespace(
            data=SimpleNamespace(category=SimpleNamespace(budgeted=100000))
        ),
        SimpleNamespace(data=SimpleNamespace(category=SimpleNamespace(budgeted=20000))),
    ]
    updated_from = SimpleNamespace(id="from-cat", budgeted=80000)
    rollback_exc = ynab.ApiException(
        status=500,
        reason="Server Error",
        body='{"error": {"id": "500", "name": "internal", '
        '"detail": "Service unavailable"}}',
    )
    categories_api.return_value.update_month_category.side_effect = [
        SimpleNamespace(data=SimpleNamespace(category=updated_from)),
        ynab.ApiException(
            status=404,
            reason="Not Found",
            body='{"error": {"id": "404", "name": "not_found", '
            '"detail": "Category not found"}}',
        ),
        rollback_exc,
        rollback_exc,
        rollback_exc,
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
        ynab_pat="x",
        ynab_default_budget_id="budget-1",
        ynab_read_only=False,
        require_write_approval=False,
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
        ynab_pat="x",
        ynab_default_budget_id="budget-1",
        ynab_read_only=False,
        require_write_approval=False,
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
        ynab_pat="x",
        ynab_default_budget_id="budget-1",
        ynab_read_only=False,
        require_write_approval=False,
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


def test_assign_budgeted_amount_retries_transient_failure(
    mocker: MockerFixture,
) -> None:
    """A transient 429 is retried and the eventual success is returned."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    client = mocker.Mock()
    categories_api = mocker.patch("ynab_mcp.tools.budgeted_amount.ynab.CategoriesApi")
    fake_category = SimpleNamespace(id="cat-1", budgeted=50000)
    categories_api.return_value.update_month_category.side_effect = [
        ynab.ApiException(status=429, reason="Too Many Requests", body=None),
        SimpleNamespace(data=SimpleNamespace(category=fake_category)),
    ]

    result = assign_budgeted_amount(client, "budget-1", "current", "cat-1", 50000)

    assert result == fake_category
    assert categories_api.return_value.update_month_category.call_count == 2


def test_move_budgeted_amount_retries_transient_failure_on_first_read(
    mocker: MockerFixture,
) -> None:
    """A transient 429 on the first read is retried; the whole move still succeeds."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    client = mocker.Mock()
    categories_api = mocker.patch("ynab_mcp.tools.budgeted_amount.ynab.CategoriesApi")
    categories_api.return_value.get_month_category_by_id.side_effect = [
        ynab.ApiException(status=429, reason="Too Many Requests", body=None),
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
    assert categories_api.return_value.get_month_category_by_id.call_count == 3


def test_manage_budgeted_amount_tool_rejects_move_without_required_fields(
    mocker: MockerFixture,
) -> None:
    """Move without from_category_id/to_category_id/amount raises before dispatch."""
    settings = Settings(
        ynab_pat="x",
        ynab_default_budget_id="budget-1",
        ynab_read_only=False,
        require_write_approval=False,
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


_APPROVAL_SETTINGS = Settings(
    ynab_pat="x", ynab_default_budget_id="budget-1", ynab_read_only=False
)
_ASSIGN = {
    "operation": "assign",
    "month": "2026-11-01",
    "category_id": "c1",
    "amount": 450000,
}
_MOVE = {
    "operation": "move",
    "month": "2026-11-01",
    "from_category_id": "c2",
    "to_category_id": "c1",
    "amount": 50000,
}


def _month_category(budgeted: int, name: str) -> SimpleNamespace:
    category = SimpleNamespace(
        budgeted=budgeted,
        name=name,
        model_dump=lambda mode="json": {"budgeted": budgeted},
    )
    return SimpleNamespace(data=SimpleNamespace(category=category))


def _patch_categories_api(mocker: MockerFixture, reads: Any) -> Any:
    """Patch the SDK's CategoriesApi and the budget-name lookup."""
    mocker.patch(
        "ynab_mcp.write_summaries.list_budgets",
        return_value=[SimpleNamespace(id="budget-1", name="Rench Budget")],
    )
    api = mocker.patch("ynab.CategoriesApi").return_value
    api.get_month_category_by_id.side_effect = reads
    api.update_month_category.return_value = _month_category(0, "written")
    return api


def _call_tool(mode: str, handler: Any, args: dict[str, Any]) -> tuple[Any, list[str]]:
    mcp = _build_registered_server(_APPROVAL_SETTINGS)
    prompts: list[str] = []

    async def recording(m: str, rt: Any, p: Any, c: Any) -> Any:
        prompts.append(m)
        return await handler(m, rt, p, c)

    async def _call() -> Any:
        async with Client(mcp, mode=mode, elicitation_handler=recording) as client:
            return await client.call_tool(
                "manage-budgeted-amount", args, raise_on_error=False
            )

    return asyncio.run(_call()), prompts


def test_assign_approve_writes(era_mode: str, mocker: MockerFixture) -> None:
    """Approving an assign writes it, after showing current and new amounts."""
    api = _patch_categories_api(
        mocker, lambda **k: _month_category(400000, "Groceries")
    )

    result, prompts = _call_tool(era_mode, approve_handler, _ASSIGN)

    assert not result.is_error
    assert "Groceries, November 2026:  $400.00 now  →  $450.00" in prompts[0]
    assert api.update_month_category.call_count == 1


def test_move_approve_writes(era_mode: str, mocker: MockerFixture) -> None:
    """Approving a move writes both categories."""
    api = _patch_categories_api(
        mocker, lambda **k: _month_category(100000, k["category_id"])
    )

    result, prompts = _call_tool(era_mode, approve_handler, _MOVE)

    assert not result.is_error
    assert "From:    c2, November 2026:  $100.00 now  →  $50.00" in prompts[0]
    assert api.update_month_category.call_count == 2


@pytest.mark.parametrize("args", [_ASSIGN, _MOVE], ids=["assign", "move"])
def test_decline_makes_no_write(
    era_mode: str, mocker: MockerFixture, args: dict[str, Any]
) -> None:
    """Declining never reaches a YNAB write."""
    api = _patch_categories_api(mocker, lambda **k: _month_category(1000, "Food"))

    result, _ = _call_tool(era_mode, decline_handler, args)

    assert result.is_error
    assert "Not applied" in result.content[0].text
    api.update_month_category.assert_not_called()


def test_budgeted_change_between_prompt_and_approval_refuses(
    era_mode: str, mocker: MockerFixture
) -> None:
    """A move whose totals changed after the prompt is refused, not applied."""
    amounts = iter([100000, 400000, 90000, 400000])
    api = _patch_categories_api(
        mocker, lambda **k: _month_category(next(amounts), "Food")
    )

    result, _ = _call_tool(era_mode, approve_handler, _MOVE)

    assert result.is_error
    assert "changed in YNAB" in result.content[0].text
    api.update_month_category.assert_not_called()


def test_invalid_month_rejected_before_prompt(
    era_mode: str, mocker: MockerFixture
) -> None:
    """A bad month is rejected without asking for approval."""
    api = _patch_categories_api(mocker, lambda **k: _month_category(1000, "Food"))

    result, prompts = _call_tool(
        era_mode, approve_handler, {**_ASSIGN, "month": "not-a-month"}
    )

    assert result.is_error
    assert "Invalid month" in result.content[0].text
    assert prompts == []
    api.get_month_category_by_id.assert_not_called()


def test_same_category_move_rejected_before_prompt(
    era_mode: str, mocker: MockerFixture
) -> None:
    """Moving a category onto itself is rejected without asking for approval."""
    _patch_categories_api(mocker, lambda **k: _month_category(1000, "Food"))

    result, prompts = _call_tool(
        era_mode, approve_handler, {**_MOVE, "to_category_id": "c2"}
    )

    assert result.is_error
    assert "must differ" in result.content[0].text
    assert prompts == []
