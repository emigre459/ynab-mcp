"""Tests for ynab_mcp.tools.scheduled_transactions."""

import asyncio
from datetime import date
from types import SimpleNamespace

import ynab
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

from ynab_mcp.config import Settings
from ynab_mcp.tools import scheduled_transactions
from ynab_mcp.tools.scheduled_transactions import (
    create_scheduled_transaction,
    delete_scheduled_transaction,
    update_scheduled_transaction,
)


def test_create_scheduled_transaction_calls_create(mocker: MockerFixture) -> None:
    """create_scheduled_transaction calls the SDK's create endpoint."""
    client = mocker.Mock()
    api = mocker.patch(
        "ynab_mcp.tools.scheduled_transactions.ynab.ScheduledTransactionsApi"
    )
    fake_scheduled = SimpleNamespace(id="st1")
    api.return_value.create_scheduled_transaction.return_value = SimpleNamespace(
        data=SimpleNamespace(scheduled_transaction=fake_scheduled)
    )

    result = create_scheduled_transaction(
        client,
        "budget-1",
        "11111111-1111-1111-1111-111111111111",
        date(2024, 3, 1),
        -50000,
        "monthly",
    )

    assert result == fake_scheduled
    call = api.return_value.create_scheduled_transaction.call_args
    assert call.kwargs["plan_id"] == "budget-1"
    wrapper = call.kwargs["data"]
    assert (
        str(wrapper.scheduled_transaction.account_id)
        == "11111111-1111-1111-1111-111111111111"
    )
    assert wrapper.scheduled_transaction.amount == -50000
    assert wrapper.scheduled_transaction.frequency == "monthly"


def test_create_scheduled_transaction_raises_tool_error_on_api_exception(
    mocker: MockerFixture,
) -> None:
    """An ApiException from the SDK surfaces as a ToolError."""
    client = mocker.Mock()
    api = mocker.patch(
        "ynab_mcp.tools.scheduled_transactions.ynab.ScheduledTransactionsApi"
    )
    api.return_value.create_scheduled_transaction.side_effect = ynab.ApiException(
        status=400,
        reason="Bad Request",
        body='{"error": {"id": "400", "name": "bad_request", '
        '"detail": "Invalid account_id"}}',
    )

    with raises(ToolError, match="Invalid account_id"):
        create_scheduled_transaction(
            client,
            "budget-1",
            "11111111-1111-1111-1111-111111111111",
            date(2024, 3, 1),
            -50000,
            "monthly",
        )


def test_update_scheduled_transaction_calls_update(mocker: MockerFixture) -> None:
    """update_scheduled_transaction calls the SDK's update endpoint."""
    client = mocker.Mock()
    api = mocker.patch(
        "ynab_mcp.tools.scheduled_transactions.ynab.ScheduledTransactionsApi"
    )
    fake_scheduled = SimpleNamespace(id="st1")
    api.return_value.update_scheduled_transaction.return_value = SimpleNamespace(
        data=SimpleNamespace(scheduled_transaction=fake_scheduled)
    )

    result = update_scheduled_transaction(
        client,
        "budget-1",
        "st1",
        "11111111-1111-1111-1111-111111111111",
        date(2024, 3, 1),
        -60000,
        "monthly",
    )

    assert result == fake_scheduled
    call = api.return_value.update_scheduled_transaction.call_args
    assert call.kwargs["plan_id"] == "budget-1"
    assert call.kwargs["scheduled_transaction_id"] == "st1"
    wrapper = call.kwargs["put_scheduled_transaction_wrapper"]
    assert wrapper.scheduled_transaction.amount == -60000


def test_update_scheduled_transaction_raises_tool_error_on_api_exception(
    mocker: MockerFixture,
) -> None:
    """An ApiException from the SDK surfaces as a ToolError."""
    client = mocker.Mock()
    api = mocker.patch(
        "ynab_mcp.tools.scheduled_transactions.ynab.ScheduledTransactionsApi"
    )
    api.return_value.update_scheduled_transaction.side_effect = ynab.ApiException(
        status=404,
        reason="Not Found",
        body='{"error": {"id": "404", "name": "not_found", '
        '"detail": "Scheduled transaction not found"}}',
    )

    with raises(ToolError, match="Scheduled transaction not found"):
        update_scheduled_transaction(
            client,
            "budget-1",
            "missing-st",
            "11111111-1111-1111-1111-111111111111",
            date(2024, 3, 1),
            -60000,
            "monthly",
        )


def test_delete_scheduled_transaction_calls_delete(mocker: MockerFixture) -> None:
    """delete_scheduled_transaction calls the SDK's delete endpoint."""
    client = mocker.Mock()
    api = mocker.patch(
        "ynab_mcp.tools.scheduled_transactions.ynab.ScheduledTransactionsApi"
    )
    fake_scheduled = SimpleNamespace(id="st1", deleted=True)
    api.return_value.delete_scheduled_transaction.return_value = SimpleNamespace(
        data=SimpleNamespace(scheduled_transaction=fake_scheduled)
    )

    result = delete_scheduled_transaction(client, "budget-1", "st1")

    assert result == fake_scheduled
    api.return_value.delete_scheduled_transaction.assert_called_once_with(
        plan_id="budget-1", scheduled_transaction_id="st1"
    )


def test_delete_scheduled_transaction_raises_tool_error_on_api_exception(
    mocker: MockerFixture,
) -> None:
    """An ApiException from the SDK surfaces as a ToolError."""
    client = mocker.Mock()
    api = mocker.patch(
        "ynab_mcp.tools.scheduled_transactions.ynab.ScheduledTransactionsApi"
    )
    api.return_value.delete_scheduled_transaction.side_effect = ynab.ApiException(
        status=404,
        reason="Not Found",
        body='{"error": {"id": "404", "name": "not_found", '
        '"detail": "Scheduled transaction not found"}}',
    )

    with raises(ToolError, match="Scheduled transaction not found"):
        delete_scheduled_transaction(client, "budget-1", "missing-st")


def _build_registered_server(settings: Settings) -> FastMCP:
    """Build a minimal FastMCP server with only manage-scheduled-transaction registered."""
    mcp = FastMCP("test")
    scheduled_transactions.register(mcp, object(), settings)  # type: ignore[arg-type]
    return mcp


def test_manage_scheduled_transaction_tool_dispatches_create(
    mocker: MockerFixture,
) -> None:
    """The create operation calls create_scheduled_transaction with the args."""
    settings = Settings(
        ynab_pat="x", ynab_default_budget_id="budget-1", ynab_read_only=False
    )
    mcp = _build_registered_server(settings)
    create_mock = mocker.patch(
        "ynab_mcp.tools.scheduled_transactions.create_scheduled_transaction",
        return_value=SimpleNamespace(model_dump=lambda mode="json": {"id": "st1"}),
    )

    async def _call() -> dict[str, object]:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "manage-scheduled-transaction",
                {
                    "operation": "create",
                    "account_id": "acct-1",
                    "date": "2024-03-01",
                    "amount": -50000,
                    "frequency": "monthly",
                },
            )
            return result.data

    result = asyncio.run(_call())

    assert result == {"id": "st1"}
    create_mock.assert_called_once_with(
        mocker.ANY,
        "budget-1",
        "acct-1",
        date(2024, 3, 1),
        -50000,
        "monthly",
        payee_id=None,
        payee_name=None,
        category_id=None,
        memo=None,
        flag_color=None,
    )


def test_manage_scheduled_transaction_tool_dispatches_update(
    mocker: MockerFixture,
) -> None:
    """The update operation calls update_scheduled_transaction with the args."""
    settings = Settings(
        ynab_pat="x", ynab_default_budget_id="budget-1", ynab_read_only=False
    )
    mcp = _build_registered_server(settings)
    update_mock = mocker.patch(
        "ynab_mcp.tools.scheduled_transactions.update_scheduled_transaction",
        return_value=SimpleNamespace(model_dump=lambda mode="json": {"id": "st1"}),
    )

    async def _call() -> dict[str, object]:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "manage-scheduled-transaction",
                {
                    "operation": "update",
                    "scheduled_transaction_id": "st1",
                    "account_id": "acct-1",
                    "date": "2024-03-01",
                    "amount": -60000,
                    "frequency": "monthly",
                },
            )
            return result.data

    result = asyncio.run(_call())

    assert result == {"id": "st1"}
    update_mock.assert_called_once_with(
        mocker.ANY,
        "budget-1",
        "st1",
        "acct-1",
        date(2024, 3, 1),
        -60000,
        "monthly",
        payee_id=None,
        payee_name=None,
        category_id=None,
        memo=None,
        flag_color=None,
    )


def test_manage_scheduled_transaction_tool_dispatches_delete(
    mocker: MockerFixture,
) -> None:
    """The delete operation calls delete_scheduled_transaction with the args."""
    settings = Settings(
        ynab_pat="x", ynab_default_budget_id="budget-1", ynab_read_only=False
    )
    mcp = _build_registered_server(settings)
    delete_mock = mocker.patch(
        "ynab_mcp.tools.scheduled_transactions.delete_scheduled_transaction",
        return_value=SimpleNamespace(
            model_dump=lambda mode="json": {"id": "st1", "deleted": True}
        ),
    )

    async def _call() -> dict[str, object]:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "manage-scheduled-transaction",
                {"operation": "delete", "scheduled_transaction_id": "st1"},
            )
            return result.data

    result = asyncio.run(_call())

    assert result == {"id": "st1", "deleted": True}
    delete_mock.assert_called_once_with(mocker.ANY, "budget-1", "st1")


def test_manage_scheduled_transaction_tool_rejects_create_without_required_fields(
    mocker: MockerFixture,
) -> None:
    """Create without account_id/date/amount/frequency raises before dispatch."""
    settings = Settings(
        ynab_pat="x", ynab_default_budget_id="budget-1", ynab_read_only=False
    )
    mcp = _build_registered_server(settings)
    create_mock = mocker.patch(
        "ynab_mcp.tools.scheduled_transactions.create_scheduled_transaction"
    )

    async def _call() -> None:
        async with Client(mcp) as client:
            await client.call_tool(
                "manage-scheduled-transaction", {"operation": "create"}
            )

    with raises(
        ToolError, match="create requires account_id, date, amount, and frequency"
    ):
        asyncio.run(_call())
    create_mock.assert_not_called()


def test_manage_scheduled_transaction_tool_rejects_update_without_id(
    mocker: MockerFixture,
) -> None:
    """Update without scheduled_transaction_id raises before dispatch."""
    settings = Settings(
        ynab_pat="x", ynab_default_budget_id="budget-1", ynab_read_only=False
    )
    mcp = _build_registered_server(settings)
    update_mock = mocker.patch(
        "ynab_mcp.tools.scheduled_transactions.update_scheduled_transaction"
    )

    async def _call() -> None:
        async with Client(mcp) as client:
            await client.call_tool(
                "manage-scheduled-transaction",
                {
                    "operation": "update",
                    "account_id": "acct-1",
                    "date": "2024-03-01",
                    "amount": -60000,
                    "frequency": "monthly",
                },
            )

    with raises(ToolError, match="update requires scheduled_transaction_id"):
        asyncio.run(_call())
    update_mock.assert_not_called()
