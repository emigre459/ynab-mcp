"""Tests for ynab_mcp.tools.transactions_write."""

from types import SimpleNamespace

import ynab
from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

from ynab_mcp.tools.transactions_write import bulk_manage_transactions


def test_bulk_manage_transactions_requires_at_least_one_operation(
    mocker: MockerFixture,
) -> None:
    """An empty operations list is a caller error, not a YNAB call."""
    client = mocker.Mock()

    with raises(ToolError, match="at least one operation"):
        bulk_manage_transactions(client, "budget-1", [])


def test_bulk_manage_transactions_rejects_unknown_action(
    mocker: MockerFixture,
) -> None:
    """An operation with an invalid action raises before any API call."""
    client = mocker.Mock()

    with raises(ToolError, match="action must be one of"):
        bulk_manage_transactions(client, "budget-1", [{"action": "archive"}])


def test_bulk_manage_transactions_rejects_update_without_id(
    mocker: MockerFixture,
) -> None:
    """An update operation missing 'id' raises before any API call."""
    client = mocker.Mock()

    with raises(ToolError, match="update requires 'id'"):
        bulk_manage_transactions(client, "budget-1", [{"action": "update"}])


def test_bulk_manage_transactions_rejects_create_without_account_id(
    mocker: MockerFixture,
) -> None:
    """A create operation missing 'account_id' raises before any API call."""
    client = mocker.Mock()

    with raises(ToolError, match="create requires 'account_id'"):
        bulk_manage_transactions(client, "budget-1", [{"action": "create"}])


def test_bulk_manage_transactions_handles_mixed_batch(mocker: MockerFixture) -> None:
    """A batch with one create, one update, and one delete runs all three."""
    client = mocker.Mock()
    transactions_api = mocker.patch(
        "ynab_mcp.tools.transactions_write.ynab.TransactionsApi"
    )
    transactions_api.return_value.create_transaction.return_value = SimpleNamespace(
        data=SimpleNamespace(transactions=[SimpleNamespace(id="new-1")])
    )
    transactions_api.return_value.update_transactions.return_value = SimpleNamespace(
        data=SimpleNamespace(transactions=[SimpleNamespace(id="txn-1")])
    )
    transactions_api.return_value.delete_transaction.return_value = SimpleNamespace(
        data=SimpleNamespace(transaction=SimpleNamespace(id="txn-2"))
    )

    operations: list[dict[str, object]] = [
        {
            "action": "create",
            "account_id": "11111111-1111-1111-1111-111111111111",
            "amount": -5000,
        },
        {
            "action": "update",
            "id": "txn-1",
            "category_id": "22222222-2222-2222-2222-222222222222",
        },
        {"action": "delete", "id": "txn-2"},
    ]

    result = bulk_manage_transactions(client, "budget-1", operations)

    assert result == [
        {"action": "create", "id": "new-1", "status": "ok", "detail": None},
        {"action": "update", "id": "txn-1", "status": "ok", "detail": None},
        {"action": "delete", "id": "txn-2", "status": "ok", "detail": None},
    ]

    create_call = transactions_api.return_value.create_transaction.call_args
    assert create_call.kwargs["plan_id"] == "budget-1"
    created_wrapper = create_call.kwargs["data"]
    assert (
        str(created_wrapper.transactions[0].account_id)
        == "11111111-1111-1111-1111-111111111111"
    )
    assert created_wrapper.transactions[0].amount == -5000

    update_call = transactions_api.return_value.update_transactions.call_args
    updated_wrapper = update_call.kwargs["data"]
    assert updated_wrapper.transactions[0].id == "txn-1"
    assert (
        str(updated_wrapper.transactions[0].category_id)
        == "22222222-2222-2222-2222-222222222222"
    )

    transactions_api.return_value.delete_transaction.assert_called_once_with(
        plan_id="budget-1", transaction_id="txn-2"
    )


def test_bulk_manage_transactions_reports_per_item_failure(
    mocker: MockerFixture,
) -> None:
    """A failure in one group doesn't block the others' results."""
    client = mocker.Mock()
    transactions_api = mocker.patch(
        "ynab_mcp.tools.transactions_write.ynab.TransactionsApi"
    )
    transactions_api.return_value.update_transactions.return_value = SimpleNamespace(
        data=SimpleNamespace(transactions=[SimpleNamespace(id="txn-1")])
    )
    transactions_api.return_value.delete_transaction.side_effect = ynab.ApiException(
        status=404,
        reason="Not Found",
        body='{"error": {"id": "404", "name": "not_found", '
        '"detail": "Transaction not found"}}',
    )

    operations: list[dict[str, object]] = [
        {
            "action": "update",
            "id": "txn-1",
            "category_id": "22222222-2222-2222-2222-222222222222",
        },
        {"action": "delete", "id": "missing-txn"},
    ]

    result = bulk_manage_transactions(client, "budget-1", operations)

    assert result[0] == {
        "action": "update",
        "id": "txn-1",
        "status": "ok",
        "detail": None,
    }
    assert result[1]["status"] == "error"
    assert result[1]["detail"] == "Transaction not found"


def test_bulk_manage_transactions_marks_whole_create_group_error_on_batch_failure(
    mocker: MockerFixture,
) -> None:
    """A failed grouped create call marks every create item as an error."""
    client = mocker.Mock()
    transactions_api = mocker.patch(
        "ynab_mcp.tools.transactions_write.ynab.TransactionsApi"
    )
    transactions_api.return_value.create_transaction.side_effect = ynab.ApiException(
        status=400,
        reason="Bad Request",
        body='{"error": {"id": "400", "name": "bad_request", '
        '"detail": "Invalid account_id"}}',
    )

    operations: list[dict[str, object]] = [
        {
            "action": "create",
            "account_id": "11111111-1111-1111-1111-111111111111",
            "amount": -1000,
        },
        {
            "action": "create",
            "account_id": "11111111-1111-1111-1111-111111111111",
            "amount": -2000,
        },
    ]

    result = bulk_manage_transactions(client, "budget-1", operations)

    assert all(item["status"] == "error" for item in result)
    assert all(item["detail"] == "Invalid account_id" for item in result)


def test_bulk_manage_transactions_reports_error_when_response_shorter_than_request(
    mocker: MockerFixture,
) -> None:
    """A create response with fewer transactions than submitted marks the gap as an error."""
    client = mocker.Mock()
    transactions_api = mocker.patch(
        "ynab_mcp.tools.transactions_write.ynab.TransactionsApi"
    )
    transactions_api.return_value.create_transaction.return_value = SimpleNamespace(
        data=SimpleNamespace(transactions=[SimpleNamespace(id="new-1")])
    )

    operations: list[dict[str, object]] = [
        {
            "action": "create",
            "account_id": "11111111-1111-1111-1111-111111111111",
            "amount": -1000,
        },
        {
            "action": "create",
            "account_id": "11111111-1111-1111-1111-111111111111",
            "amount": -2000,
        },
    ]

    result = bulk_manage_transactions(client, "budget-1", operations)

    assert result[0] == {
        "action": "create",
        "id": "new-1",
        "status": "ok",
        "detail": None,
    }
    assert result[1]["status"] == "error"
    assert result[1]["id"] is None
    assert "did not include a result" in str(result[1]["detail"])
