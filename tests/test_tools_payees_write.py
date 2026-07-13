"""Tests for ynab_mcp.tools.payees_write."""

from types import SimpleNamespace

import ynab
from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

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
