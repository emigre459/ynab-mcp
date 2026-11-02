"""Tests for ynab_mcp.tools.scheduled_transactions."""

import asyncio
from datetime import date
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
        ynab_pat="x",
        ynab_default_budget_id="budget-1",
        ynab_read_only=False,
        require_write_approval=False,
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
        ynab_pat="x",
        ynab_default_budget_id="budget-1",
        ynab_read_only=False,
        require_write_approval=False,
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
        ynab_pat="x",
        ynab_default_budget_id="budget-1",
        ynab_read_only=False,
        require_write_approval=False,
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
        ynab_pat="x",
        ynab_default_budget_id="budget-1",
        ynab_read_only=False,
        require_write_approval=False,
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


def test_create_scheduled_transaction_retries_transient_429(
    mocker: MockerFixture,
) -> None:
    """A transient 429 is retried even though this create is 429-only."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    client = mocker.Mock()
    api = mocker.patch(
        "ynab_mcp.tools.scheduled_transactions.ynab.ScheduledTransactionsApi"
    )
    fake_scheduled = SimpleNamespace(id="st1")
    api.return_value.create_scheduled_transaction.side_effect = [
        ynab.ApiException(status=429, reason="Too Many Requests", body=None),
        SimpleNamespace(data=SimpleNamespace(scheduled_transaction=fake_scheduled)),
    ]

    result = create_scheduled_transaction(
        client,
        "budget-1",
        "11111111-1111-1111-1111-111111111111",
        date(2024, 3, 1),
        -50000,
        "monthly",
    )

    assert result == fake_scheduled
    assert api.return_value.create_scheduled_transaction.call_count == 2


def test_create_scheduled_transaction_does_not_retry_5xx(
    mocker: MockerFixture,
) -> None:
    """A 5xx on create is ambiguous (may have already landed) -- no retry."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    client = mocker.Mock()
    api = mocker.patch(
        "ynab_mcp.tools.scheduled_transactions.ynab.ScheduledTransactionsApi"
    )
    exc = ynab.ApiException(
        status=500,
        reason="Internal Server Error",
        body='{"error": {"id": "500", "name": "internal", '
        '"detail": "Service unavailable"}}',
    )
    api.return_value.create_scheduled_transaction.side_effect = [
        exc,
        SimpleNamespace(data=SimpleNamespace(scheduled_transaction=SimpleNamespace())),
    ]

    with raises(ToolError, match="Service unavailable"):
        create_scheduled_transaction(
            client,
            "budget-1",
            "11111111-1111-1111-1111-111111111111",
            date(2024, 3, 1),
            -50000,
            "monthly",
        )

    assert api.return_value.create_scheduled_transaction.call_count == 1


def test_update_scheduled_transaction_retries_transient_failure(
    mocker: MockerFixture,
) -> None:
    """A transient 429 is retried and the eventual success is returned."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    client = mocker.Mock()
    api = mocker.patch(
        "ynab_mcp.tools.scheduled_transactions.ynab.ScheduledTransactionsApi"
    )
    fake_scheduled = SimpleNamespace(id="st1")
    api.return_value.update_scheduled_transaction.side_effect = [
        ynab.ApiException(status=429, reason="Too Many Requests", body=None),
        SimpleNamespace(data=SimpleNamespace(scheduled_transaction=fake_scheduled)),
    ]

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
    assert api.return_value.update_scheduled_transaction.call_count == 2


def test_delete_scheduled_transaction_retries_transient_failure(
    mocker: MockerFixture,
) -> None:
    """A transient 429 is retried and the eventual success is returned."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    client = mocker.Mock()
    api = mocker.patch(
        "ynab_mcp.tools.scheduled_transactions.ynab.ScheduledTransactionsApi"
    )
    fake_scheduled = SimpleNamespace(id="st1", deleted=True)
    api.return_value.delete_scheduled_transaction.side_effect = [
        ynab.ApiException(status=429, reason="Too Many Requests", body=None),
        SimpleNamespace(data=SimpleNamespace(scheduled_transaction=fake_scheduled)),
    ]

    result = delete_scheduled_transaction(client, "budget-1", "st1")

    assert result == fake_scheduled
    assert api.return_value.delete_scheduled_transaction.call_count == 2


def test_manage_scheduled_transaction_tool_rejects_update_without_id(
    mocker: MockerFixture,
) -> None:
    """Update without scheduled_transaction_id raises before dispatch."""
    settings = Settings(
        ynab_pat="x",
        ynab_default_budget_id="budget-1",
        ynab_read_only=False,
        require_write_approval=False,
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


_APPROVAL_SETTINGS = Settings(
    ynab_pat="x", ynab_default_budget_id="budget-1", ynab_read_only=False
)
_CREATE = {
    "operation": "create",
    "account_id": "acct-1",
    "date": "2030-03-01",
    "amount": -50000,
    "frequency": "monthly",
}
_UPDATE = {**_CREATE, "operation": "update", "scheduled_transaction_id": "st1"}
_DELETE = {"operation": "delete", "scheduled_transaction_id": "st1"}
_MODULE = "ynab_mcp.tools.scheduled_transactions"


def _existing(amount: int = -15490) -> SimpleNamespace:
    detail = SimpleNamespace(
        date_first=date(2030, 3, 1),
        frequency="monthly",
        amount=amount,
        account_id="acct-1",
        account_name="Chase Checking",
        payee_id="p2",
        payee_name="Netflix",
        category_id=None,
        category_name=None,
        memo=None,
        flag_color=None,
    )
    return SimpleNamespace(data=SimpleNamespace(scheduled_transaction=detail))


def _patch_lookups(mocker: MockerFixture, reads: Any) -> None:
    prefix = "ynab_mcp.write_summaries"
    mocker.patch(
        f"{prefix}.list_budgets",
        return_value=[SimpleNamespace(id="budget-1", name="Rench Budget")],
    )
    mocker.patch(
        f"{prefix}.list_accounts",
        return_value=[SimpleNamespace(id="acct-1", name="Chase Checking")],
    )
    mocker.patch(f"{prefix}.list_categories", return_value=[])
    mocker.patch(f"{prefix}.list_payees", return_value=[])
    api = mocker.patch("ynab.ScheduledTransactionsApi").return_value
    api.get_scheduled_transaction_by_id.side_effect = reads


def _call_tool(mode: str, handler: Any, args: dict[str, Any]) -> tuple[Any, list[str]]:
    mcp = _build_registered_server(_APPROVAL_SETTINGS)
    prompts: list[str] = []

    async def recording(m: str, rt: Any, p: Any, c: Any) -> Any:
        prompts.append(m)
        return await handler(m, rt, p, c)

    async def _call() -> Any:
        async with Client(mcp, mode=mode, elicitation_handler=recording) as client:
            return await client.call_tool(
                "manage-scheduled-transaction", args, raise_on_error=False
            )

    return asyncio.run(_call()), prompts


_WRITTEN = SimpleNamespace(model_dump=lambda mode="json": {"id": "st1"})


def test_create_approve_writes(era_mode: str, mocker: MockerFixture) -> None:
    """Approving a create writes it, after naming the account in the prompt."""
    _patch_lookups(mocker, lambda **k: _existing())
    write = mocker.patch(
        f"{_MODULE}.create_scheduled_transaction", return_value=_WRITTEN
    )

    result, prompts = _call_tool(era_mode, approve_handler, _CREATE)

    assert result.data == {"id": "st1"}
    assert "Chase Checking" in prompts[0]
    write.assert_called_once()


def test_update_approve_writes(era_mode: str, mocker: MockerFixture) -> None:
    """Approving an update writes it, after showing old and new amounts."""
    _patch_lookups(mocker, lambda **k: _existing())
    write = mocker.patch(
        f"{_MODULE}.update_scheduled_transaction", return_value=_WRITTEN
    )

    result, prompts = _call_tool(era_mode, approve_handler, _UPDATE)

    assert result.data == {"id": "st1"}
    assert "-$15.49  →  -$50.00" in prompts[0]
    write.assert_called_once()


def test_delete_approve_writes(era_mode: str, mocker: MockerFixture) -> None:
    """Approving a delete writes it, after identifying what disappears."""
    _patch_lookups(mocker, lambda **k: _existing())
    write = mocker.patch(
        f"{_MODULE}.delete_scheduled_transaction", return_value=_WRITTEN
    )

    result, prompts = _call_tool(era_mode, approve_handler, _DELETE)

    assert result.data == {"id": "st1"}
    assert "Netflix, 2030-03-01, -$15.49, monthly, Chase Checking" in prompts[0]
    write.assert_called_once_with(mocker.ANY, "budget-1", "st1")


@pytest.mark.parametrize(
    ("args", "function"),
    [
        (_CREATE, "create_scheduled_transaction"),
        (_UPDATE, "update_scheduled_transaction"),
        (_DELETE, "delete_scheduled_transaction"),
    ],
    ids=["create", "update", "delete"],
)
def test_decline_makes_no_write(
    era_mode: str, mocker: MockerFixture, args: dict[str, Any], function: str
) -> None:
    """Declining never reaches a YNAB write."""
    _patch_lookups(mocker, lambda **k: _existing())
    write = mocker.patch(f"{_MODULE}.{function}")

    result, _ = _call_tool(era_mode, decline_handler, args)

    assert result.is_error
    assert "Not applied" in result.content[0].text
    write.assert_not_called()


def test_scheduled_change_refuses(era_mode: str, mocker: MockerFixture) -> None:
    """An item changed after the prompt is refused, not overwritten."""
    amounts = iter([-15490, -99000])
    _patch_lookups(mocker, lambda **k: _existing(next(amounts)))
    write = mocker.patch(f"{_MODULE}.update_scheduled_transaction")

    result, _ = _call_tool(era_mode, approve_handler, _UPDATE)

    assert result.is_error
    assert "changed in YNAB" in result.content[0].text
    write.assert_not_called()


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ({"operation": "create", "account_id": "a"}, "create requires"),
        (
            {k: v for k, v in _UPDATE.items() if k != "scheduled_transaction_id"},
            "update requires scheduled_transaction_id",
        ),
        ({"operation": "delete"}, "delete requires"),
    ],
    ids=["create", "update", "delete"],
)
def test_missing_fields_rejected_before_prompt(
    era_mode: str, mocker: MockerFixture, args: dict[str, Any], message: str
) -> None:
    """A call that would be rejected anyway never asks for approval."""
    _patch_lookups(mocker, lambda **k: _existing())

    result, prompts = _call_tool(era_mode, approve_handler, args)

    assert result.is_error
    assert message in result.content[0].text
    assert prompts == []
