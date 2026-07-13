"""Tests for ynab_mcp.tools.find_amazon_transactions."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

from amazonorders.exception import AmazonOrdersAuthError
from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

from ynab_mcp.tools.find_amazon_transactions import find_amazon_transactions


def _ynab_txn(
    mocker: MockerFixture, id_: str, amount: int, txn_date: date, payee: str
) -> Mock:
    txn = mocker.Mock()
    txn.id = id_
    txn.amount = amount
    txn.var_date = txn_date
    txn.payee_name = payee
    txn.model_dump.return_value = {"id": id_, "amount": amount, "payee_name": payee}
    return txn


def _amazon_txn(
    order_number: str,
    grand_total: float,
    completed_date: date,
    seller: str = "Amazon.com",
    is_refund: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        order_number=order_number,
        grand_total=grand_total,
        completed_date=completed_date,
        payment_method="Visa ...1234",
        seller=seller,
        is_refund=is_refund,
    )


def _order(titles: list[str]) -> SimpleNamespace:
    return SimpleNamespace(items=[SimpleNamespace(title=t) for t in titles])


def test_find_amazon_transactions_returns_exact_match_with_reasoning(
    mocker: MockerFixture,
) -> None:
    """An exact amount+date pair comes back in matches with item detail."""
    ynab_client = mocker.Mock()
    list_transactions = mocker.patch(
        "ynab_mcp.tools.find_amazon_transactions.list_transactions"
    )
    list_transactions.return_value = [
        _ynab_txn(mocker, "y1", -259900, date(2026, 6, 1), "Amazon.com"),
    ]
    amazon_transactions_client = mocker.Mock()
    amazon_transactions_client.get_transactions.return_value = [
        _amazon_txn("111-1111111", -259.90, date(2026, 6, 1)),
    ]
    amazon_orders_client = mocker.Mock()
    amazon_orders_client.get_order.return_value = _order(["Widget"])

    result = find_amazon_transactions(
        ynab_client, amazon_transactions_client, amazon_orders_client, "budget-1"
    )

    assert len(result["matches"]) == 1  # type: ignore[arg-type]
    match = result["matches"][0]  # type: ignore[index]
    assert match["ynab_transaction"] == {
        "id": "y1",
        "amount": -259900,
        "payee_name": "Amazon.com",
    }
    assert match["order_number"] == "111-1111111"
    assert match["classification"] == "exact"
    assert match["same_day"] is True
    assert "Widget" in match["reasoning"]
    assert match["amazon_transaction"]["grand_total"] == -259.90
    assert result["ambiguous"] == []
    assert result["unmatched"] == []
    amazon_orders_client.get_order.assert_called_once_with("111-1111111")


def test_find_amazon_transactions_excludes_refunds_and_whole_foods(
    mocker: MockerFixture,
) -> None:
    """Refunds and Whole Foods charges never become match candidates."""
    ynab_client = mocker.Mock()
    list_transactions = mocker.patch(
        "ynab_mcp.tools.find_amazon_transactions.list_transactions"
    )
    list_transactions.return_value = [
        _ynab_txn(mocker, "y1", -5000, date(2026, 6, 1), "Amazon.com"),
    ]
    amazon_transactions_client = mocker.Mock()
    amazon_transactions_client.get_transactions.return_value = [
        _amazon_txn("111-1111111", 50.00, date(2026, 6, 1), is_refund=True),
        _amazon_txn(
            "222-2222222", -50.00, date(2026, 6, 1), seller="Whole Foods Market"
        ),
    ]
    amazon_orders_client = mocker.Mock()

    result = find_amazon_transactions(
        ynab_client, amazon_transactions_client, amazon_orders_client, "budget-1"
    )

    assert result["matches"] == []
    assert result["unmatched"][0]["ynab_transaction"]["id"] == "y1"  # type: ignore[index]
    amazon_orders_client.get_order.assert_not_called()


def test_find_amazon_transactions_ignores_non_amazon_payees(
    mocker: MockerFixture,
) -> None:
    """A payee that doesn't look like Amazon never reaches the matcher."""
    ynab_client = mocker.Mock()
    list_transactions = mocker.patch(
        "ynab_mcp.tools.find_amazon_transactions.list_transactions"
    )
    list_transactions.return_value = [
        _ynab_txn(mocker, "y1", -5000, date(2026, 6, 1), "Local Grocery Store"),
    ]
    amazon_transactions_client = mocker.Mock()
    amazon_transactions_client.get_transactions.return_value = []
    amazon_orders_client = mocker.Mock()

    result = find_amazon_transactions(
        ynab_client, amazon_transactions_client, amazon_orders_client, "budget-1"
    )

    assert result["matches"] == []
    assert result["ambiguous"] == []
    assert result["unmatched"] == []


def test_find_amazon_transactions_surfaces_ambiguous_candidates(
    mocker: MockerFixture,
) -> None:
    """Tied Amazon candidates are surfaced, not silently resolved."""
    ynab_client = mocker.Mock()
    list_transactions = mocker.patch(
        "ynab_mcp.tools.find_amazon_transactions.list_transactions"
    )
    list_transactions.return_value = [
        _ynab_txn(mocker, "y1", -30000, date(2026, 6, 5), "Amazon.com"),
    ]
    amazon_transactions_client = mocker.Mock()
    amazon_transactions_client.get_transactions.return_value = [
        _amazon_txn("333-1111111", -30.00, date(2026, 6, 4)),
        _amazon_txn("333-2222222", -30.00, date(2026, 6, 6)),
    ]
    amazon_orders_client = mocker.Mock()

    result = find_amazon_transactions(
        ynab_client, amazon_transactions_client, amazon_orders_client, "budget-1"
    )

    assert result["matches"] == []
    assert len(result["ambiguous"]) == 1  # type: ignore[arg-type]
    ambiguous = result["ambiguous"][0]  # type: ignore[index]
    assert ambiguous["ynab_transaction"]["id"] == "y1"
    assert len(ambiguous["candidates"]) == 2
    order_numbers = {c["order_number"] for c in ambiguous["candidates"]}
    assert order_numbers == {"333-1111111", "333-2222222"}


def test_find_amazon_transactions_translates_auth_error(mocker: MockerFixture) -> None:
    """An expired Amazon session surfaces as a ToolError with remediation."""
    ynab_client = mocker.Mock()
    mocker.patch(
        "ynab_mcp.tools.find_amazon_transactions.list_transactions",
        return_value=[_ynab_txn(mocker, "y1", -3000, date(2026, 6, 5), "Amazon.com")],
    )
    amazon_transactions_client = mocker.Mock()
    amazon_transactions_client.get_transactions.side_effect = AmazonOrdersAuthError(
        "expired"
    )
    amazon_orders_client = mocker.Mock()

    with raises(ToolError, match="scripts/amazon_login.py"):
        find_amazon_transactions(
            ynab_client, amazon_transactions_client, amazon_orders_client, "budget-1"
        )
