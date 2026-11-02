"""Tests for ynab_mcp.tools.payees_write."""

import asyncio
from types import SimpleNamespace
from typing import Any

import tenacity
import ynab
from conftest import approve_handler, decline_handler
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

from ynab_mcp.config import Settings
from ynab_mcp.tools import payees_write
from ynab_mcp.tools.payees_write import merge_payees, rename_payee


def test_rename_payee_calls_update_payee(mocker: MockerFixture) -> None:
    """rename_payee calls PayeesApi.update_payee with the new name."""
    client = mocker.Mock()
    payees_api = mocker.patch("ynab_mcp.tools.payees_write.ynab.PayeesApi")
    fake_payee = SimpleNamespace(id="p1", name="Amazon")
    payees_api.return_value.update_payee.return_value = SimpleNamespace(
        data=SimpleNamespace(payee=fake_payee)
    )

    result = rename_payee(client, "budget-1", "p1", "Amazon")

    assert result == fake_payee
    call = payees_api.return_value.update_payee.call_args
    assert call.kwargs["plan_id"] == "budget-1"
    assert call.kwargs["payee_id"] == "p1"
    assert call.kwargs["data"].payee.name == "Amazon"


def test_rename_payee_raises_tool_error_on_api_exception(
    mocker: MockerFixture,
) -> None:
    """An ApiException from the SDK surfaces as a ToolError."""
    client = mocker.Mock()
    payees_api = mocker.patch("ynab_mcp.tools.payees_write.ynab.PayeesApi")
    payees_api.return_value.update_payee.side_effect = ynab.ApiException(
        status=404,
        reason="Not Found",
        body='{"error": {"id": "404", "name": "not_found", '
        '"detail": "Payee not found"}}',
    )

    with raises(ToolError, match="Payee not found"):
        rename_payee(client, "budget-1", "missing-payee", "Amazon")


def test_merge_payees_renames_source_to_target_name(mocker: MockerFixture) -> None:
    """merge_payees reads the target's name and renames the source to match."""
    client = mocker.Mock()
    payees_api = mocker.patch("ynab_mcp.tools.payees_write.ynab.PayeesApi")
    target_payee = SimpleNamespace(id="p2", name="Amazon.com")
    merged_payee = SimpleNamespace(id="p1", name="Amazon.com")
    payees_api.return_value.get_payee_by_id.return_value = SimpleNamespace(
        data=SimpleNamespace(payee=target_payee)
    )
    payees_api.return_value.update_payee.return_value = SimpleNamespace(
        data=SimpleNamespace(payee=merged_payee)
    )

    result = merge_payees(client, "budget-1", "p1", "p2")

    assert result == merged_payee
    payees_api.return_value.get_payee_by_id.assert_called_once_with(
        plan_id="budget-1", payee_id="p2"
    )
    update_call = payees_api.return_value.update_payee.call_args
    assert update_call.kwargs["plan_id"] == "budget-1"
    assert update_call.kwargs["payee_id"] == "p1"
    assert update_call.kwargs["data"].payee.name == "Amazon.com"


def test_merge_payees_raises_tool_error_on_api_exception(
    mocker: MockerFixture,
) -> None:
    """An ApiException from the SDK surfaces as a ToolError."""
    client = mocker.Mock()
    payees_api = mocker.patch("ynab_mcp.tools.payees_write.ynab.PayeesApi")
    payees_api.return_value.get_payee_by_id.side_effect = ynab.ApiException(
        status=404,
        reason="Not Found",
        body='{"error": {"id": "404", "name": "not_found", '
        '"detail": "Payee not found"}}',
    )

    with raises(ToolError, match="Payee not found"):
        merge_payees(client, "budget-1", "p1", "missing-payee")


def _build_registered_server(settings: Settings) -> FastMCP:
    """Build a minimal FastMCP server with only manage-payees registered."""
    mcp = FastMCP("test")
    payees_write.register(mcp, object(), settings)  # type: ignore[arg-type]
    return mcp


def test_manage_payees_tool_dispatches_rename(mocker: MockerFixture) -> None:
    """The rename operation calls rename_payee with the caller's arguments."""
    settings = Settings(
        ynab_pat="x",
        ynab_default_budget_id="budget-1",
        ynab_read_only=False,
        require_write_approval=False,
    )
    mcp = _build_registered_server(settings)
    rename_mock = mocker.patch(
        "ynab_mcp.tools.payees_write.rename_payee",
        return_value=SimpleNamespace(
            model_dump=lambda mode="json": {"id": "p1", "name": "Amazon"}
        ),
    )

    async def _call() -> dict[str, object]:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "manage-payees",
                {"operation": "rename", "payee_id": "p1", "new_name": "Amazon"},
            )
            return result.data

    result = asyncio.run(_call())

    assert result == {"id": "p1", "name": "Amazon"}
    rename_mock.assert_called_once_with(mocker.ANY, "budget-1", "p1", "Amazon")


def test_manage_payees_tool_dispatches_merge(mocker: MockerFixture) -> None:
    """The merge operation calls merge_payees with the caller's arguments."""
    settings = Settings(
        ynab_pat="x",
        ynab_default_budget_id="budget-1",
        ynab_read_only=False,
        require_write_approval=False,
    )
    mcp = _build_registered_server(settings)
    merge_mock = mocker.patch(
        "ynab_mcp.tools.payees_write.merge_payees",
        return_value=SimpleNamespace(
            model_dump=lambda mode="json": {"id": "p2", "name": "Amazon.com"}
        ),
    )

    async def _call() -> dict[str, object]:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "manage-payees",
                {
                    "operation": "merge",
                    "source_payee_id": "p1",
                    "target_payee_id": "p2",
                },
            )
            return result.data

    result = asyncio.run(_call())

    assert result == {"id": "p2", "name": "Amazon.com"}
    merge_mock.assert_called_once_with(mocker.ANY, "budget-1", "p1", "p2")


def test_manage_payees_tool_rejects_rename_without_new_name(
    mocker: MockerFixture,
) -> None:
    """Rename without new_name raises before calling rename_payee."""
    settings = Settings(
        ynab_pat="x",
        ynab_default_budget_id="budget-1",
        ynab_read_only=False,
        require_write_approval=False,
    )
    mcp = _build_registered_server(settings)
    rename_mock = mocker.patch("ynab_mcp.tools.payees_write.rename_payee")

    async def _call() -> None:
        async with Client(mcp) as client:
            await client.call_tool(
                "manage-payees", {"operation": "rename", "payee_id": "p1"}
            )

    with raises(ToolError, match="rename requires payee_id and new_name"):
        asyncio.run(_call())
    rename_mock.assert_not_called()


def test_manage_payees_tool_rejects_merge_without_target(
    mocker: MockerFixture,
) -> None:
    """Merge without target_payee_id raises before calling merge_payees."""
    settings = Settings(
        ynab_pat="x",
        ynab_default_budget_id="budget-1",
        ynab_read_only=False,
        require_write_approval=False,
    )
    mcp = _build_registered_server(settings)
    merge_mock = mocker.patch("ynab_mcp.tools.payees_write.merge_payees")

    async def _call() -> None:
        async with Client(mcp) as client:
            await client.call_tool(
                "manage-payees", {"operation": "merge", "source_payee_id": "p1"}
            )

    with raises(ToolError, match="merge requires source_payee_id and target_payee_id"):
        asyncio.run(_call())
    merge_mock.assert_not_called()


def test_rename_payee_retries_transient_failure(mocker: MockerFixture) -> None:
    """A transient 429 is retried and the eventual success is returned."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    client = mocker.Mock()
    payees_api = mocker.patch("ynab_mcp.tools.payees_write.ynab.PayeesApi")
    fake_payee = SimpleNamespace(id="p1", name="Amazon")
    payees_api.return_value.update_payee.side_effect = [
        ynab.ApiException(status=429, reason="Too Many Requests", body=None),
        SimpleNamespace(data=SimpleNamespace(payee=fake_payee)),
    ]

    result = rename_payee(client, "budget-1", "p1", "Amazon")

    assert result == fake_payee
    assert payees_api.return_value.update_payee.call_count == 2


def test_merge_payees_retries_transient_failure_on_read(
    mocker: MockerFixture,
) -> None:
    """A transient 429 on the target read is retried; the merge still succeeds."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    client = mocker.Mock()
    payees_api = mocker.patch("ynab_mcp.tools.payees_write.ynab.PayeesApi")
    target_payee = SimpleNamespace(id="p2", name="Amazon.com")
    merged_payee = SimpleNamespace(id="p1", name="Amazon.com")
    payees_api.return_value.get_payee_by_id.side_effect = [
        ynab.ApiException(status=429, reason="Too Many Requests", body=None),
        SimpleNamespace(data=SimpleNamespace(payee=target_payee)),
    ]
    payees_api.return_value.update_payee.return_value = SimpleNamespace(
        data=SimpleNamespace(payee=merged_payee)
    )

    result = merge_payees(client, "budget-1", "p1", "p2")

    assert result == merged_payee
    assert payees_api.return_value.get_payee_by_id.call_count == 2


def _approval_settings() -> Settings:
    return Settings(
        ynab_pat="x", ynab_default_budget_id="budget-1", ynab_read_only=False
    )


def _patch_names(mocker: MockerFixture) -> None:
    mocker.patch(
        "ynab_mcp.write_summaries.list_budgets",
        return_value=[SimpleNamespace(id="budget-1", name="Rench Budget")],
    )
    mocker.patch(
        "ynab_mcp.write_summaries.list_payees",
        return_value=[
            SimpleNamespace(id="p1", name="AMZN Mktp"),
            SimpleNamespace(id="p2", name="Amazon"),
        ],
    )


def _call_with_handler(mcp: FastMCP, mode: str, handler: Any, args: dict) -> Any:
    prompts: list[str] = []

    async def recording(m: str, rt: Any, p: Any, c: Any) -> Any:
        prompts.append(m)
        return await handler(m, rt, p, c)

    async def _call() -> Any:
        async with Client(mcp, mode=mode, elicitation_handler=recording) as client:
            return await client.call_tool("manage-payees", args, raise_on_error=False)

    return asyncio.run(_call()), prompts


def test_manage_payees_rename_approve(era_mode: str, mocker: MockerFixture) -> None:
    """Approving a rename performs it, after showing names in the prompt."""
    _patch_names(mocker)
    mcp = _build_registered_server(_approval_settings())
    rename_mock = mocker.patch(
        "ynab_mcp.tools.payees_write.rename_payee",
        return_value=SimpleNamespace(model_dump=lambda mode="json": {"id": "p1"}),
    )

    result, prompts = _call_with_handler(
        mcp,
        era_mode,
        approve_handler,
        {"operation": "rename", "payee_id": "p1", "new_name": "Amazon"},
    )

    assert result.data == {"id": "p1"}
    assert '"AMZN Mktp"  →  "Amazon"' in prompts[0]
    rename_mock.assert_called_once_with(mocker.ANY, "budget-1", "p1", "Amazon")


def test_manage_payees_merge_approve(era_mode: str, mocker: MockerFixture) -> None:
    """Approving a merge performs it, after naming both payees in the prompt."""
    _patch_names(mocker)
    mcp = _build_registered_server(_approval_settings())
    merge_mock = mocker.patch(
        "ynab_mcp.tools.payees_write.merge_payees",
        return_value=SimpleNamespace(model_dump=lambda mode="json": {"id": "p2"}),
    )

    result, prompts = _call_with_handler(
        mcp,
        era_mode,
        approve_handler,
        {"operation": "merge", "source_payee_id": "p1", "target_payee_id": "p2"},
    )

    assert result.data == {"id": "p2"}
    assert '"AMZN Mktp" into "Amazon"' in prompts[0]
    merge_mock.assert_called_once_with(mocker.ANY, "budget-1", "p1", "p2")


def test_manage_payees_decline_makes_no_write(
    era_mode: str, mocker: MockerFixture
) -> None:
    """Declining never reaches the YNAB write call."""
    _patch_names(mocker)
    mcp = _build_registered_server(_approval_settings())
    rename_mock = mocker.patch("ynab_mcp.tools.payees_write.rename_payee")

    result, _ = _call_with_handler(
        mcp,
        era_mode,
        decline_handler,
        {"operation": "rename", "payee_id": "p1", "new_name": "Amazon"},
    )

    assert result.is_error
    assert "Not applied" in result.content[0].text
    rename_mock.assert_not_called()


def test_manage_payees_read_only_shows_no_prompt(
    era_mode: str, mocker: MockerFixture
) -> None:
    """require_writable still runs first: read-only never prompts or reads."""
    budgets = mocker.patch("ynab_mcp.write_summaries.list_budgets")
    mcp = _build_registered_server(
        Settings(ynab_pat="x", ynab_default_budget_id="budget-1", ynab_read_only=True)
    )

    result, prompts = _call_with_handler(
        mcp,
        era_mode,
        approve_handler,
        {"operation": "rename", "payee_id": "p1", "new_name": "Amazon"},
    )

    assert result.is_error
    assert "YNAB_READ_ONLY" in result.content[0].text
    assert prompts == []
    budgets.assert_not_called()


def test_manage_payees_missing_fields_rejected_before_prompt(
    era_mode: str, mocker: MockerFixture
) -> None:
    """A call that would be rejected anyway never asks for approval."""
    budgets = mocker.patch("ynab_mcp.write_summaries.list_budgets")
    mcp = _build_registered_server(_approval_settings())

    result, prompts = _call_with_handler(
        mcp, era_mode, approve_handler, {"operation": "rename", "payee_id": "p1"}
    )

    assert result.is_error
    assert "rename requires" in result.content[0].text
    assert prompts == []
    budgets.assert_not_called()
