"""Tests for ynab_mcp.tools.find_amazon_transactions."""

import threading
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

from amazonorders.exception import AmazonOrdersAuthError
from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

from ynab_mcp.tools.find_amazon_transactions import find_amazon_transactions


def _ynab_txn(
    mocker: MockerFixture,
    id_: str,
    amount: int,
    txn_date: date,
    payee: str,
    approved: bool = False,
) -> Mock:
    txn = mocker.Mock()
    txn.id = id_
    txn.amount = amount
    txn.var_date = txn_date
    txn.payee_name = payee
    txn.approved = approved
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
        ynab_client,
        amazon_transactions_client,
        lambda: amazon_orders_client,
        "budget-1",
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
        ynab_client,
        amazon_transactions_client,
        lambda: amazon_orders_client,
        "budget-1",
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
        ynab_client,
        amazon_transactions_client,
        lambda: amazon_orders_client,
        "budget-1",
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
        ynab_client,
        amazon_transactions_client,
        lambda: amazon_orders_client,
        "budget-1",
    )

    assert result["matches"] == []
    assert len(result["ambiguous"]) == 1  # type: ignore[arg-type]
    ambiguous = result["ambiguous"][0]  # type: ignore[index]
    assert ambiguous["ynab_transaction"]["id"] == "y1"
    assert len(ambiguous["candidates"]) == 2
    order_numbers = {c["order_number"] for c in ambiguous["candidates"]}
    assert order_numbers == {"333-1111111", "333-2222222"}


def test_find_amazon_transactions_matches_blank_order_numbers_without_enrichment(
    mocker: MockerFixture,
) -> None:
    """Amazon transactions with no parseable order number still match.

    amazon-orders' Transaction._parse_order_number() can legitimately
    return "" for certain transaction shapes (e.g. some digital/
    subscription charges, confirmed via live testing against a real
    Audible charge). These must still be matchable -- an unparseable
    order number doesn't mean the charge isn't real -- but calling
    AmazonOrders.get_order("") would fail, so enrichment is skipped
    (reasoning has no item-detail suffix) and the output order_number is
    the blank string as-is.
    """
    ynab_client = mocker.Mock()
    list_transactions = mocker.patch(
        "ynab_mcp.tools.find_amazon_transactions.list_transactions"
    )
    list_transactions.return_value = [
        _ynab_txn(mocker, "y1", -5000, date(2026, 6, 1), "Amazon.com"),
    ]
    amazon_transactions_client = mocker.Mock()
    amazon_transactions_client.get_transactions.return_value = [
        _amazon_txn("", -5.00, date(2026, 6, 1)),
    ]
    amazon_orders_client = mocker.Mock()

    result = find_amazon_transactions(
        ynab_client,
        amazon_transactions_client,
        lambda: amazon_orders_client,
        "budget-1",
    )

    assert len(result["matches"]) == 1  # type: ignore[arg-type]
    match = result["matches"][0]  # type: ignore[index]
    assert match["order_number"] == ""
    assert match["classification"] == "exact"
    assert match["split_group"] == []
    assert "order #" not in match["reasoning"]
    assert result["ambiguous"] == []
    assert result["unmatched"] == []
    amazon_orders_client.get_order.assert_not_called()


def test_find_amazon_transactions_does_not_fake_group_blank_order_numbers(
    mocker: MockerFixture,
) -> None:
    """Two unrelated blank-order-number matches never group as split-shipment.

    Both share the same (blank) real order_number, but they must not be
    treated as legs of one split-shipment order -- there is no evidence
    they're actually related.
    """
    ynab_client = mocker.Mock()
    list_transactions = mocker.patch(
        "ynab_mcp.tools.find_amazon_transactions.list_transactions"
    )
    list_transactions.return_value = [
        _ynab_txn(mocker, "y1", -5000, date(2026, 6, 1), "Amazon.com"),
        _ynab_txn(mocker, "y2", -7500, date(2026, 6, 2), "Amazon.com"),
    ]
    amazon_transactions_client = mocker.Mock()
    amazon_transactions_client.get_transactions.return_value = [
        _amazon_txn("", -5.00, date(2026, 6, 1)),
        _amazon_txn("", -7.50, date(2026, 6, 2)),
    ]
    amazon_orders_client = mocker.Mock()

    result = find_amazon_transactions(
        ynab_client,
        amazon_transactions_client,
        lambda: amazon_orders_client,
        "budget-1",
    )

    assert len(result["matches"]) == 2  # type: ignore[arg-type]
    for match in result["matches"]:  # type: ignore[attr-defined]
        assert match["classification"] != "split-shipment"
        assert match["split_group"] == []
    amazon_orders_client.get_order.assert_not_called()


def test_find_amazon_transactions_excludes_approved_by_default(
    mocker: MockerFixture,
) -> None:
    """Already-approved YNAB transactions are excluded from the result set.

    approved=True means a human already reviewed and confirmed the
    imported bank transaction in YNAB -- it's orthogonal to whether
    anyone cross-referenced it against the actual Amazon order, but it's
    the signal the user wants to treat as "already handled, don't
    resurface." Excluded entirely (not matches, not ambiguous, not
    unmatched) so the result set stays focused on outstanding review work.
    """
    ynab_client = mocker.Mock()
    list_transactions = mocker.patch(
        "ynab_mcp.tools.find_amazon_transactions.list_transactions"
    )
    list_transactions.return_value = [
        _ynab_txn(mocker, "y1", -259900, date(2026, 6, 1), "Amazon.com", approved=True),
    ]
    amazon_transactions_client = mocker.Mock()
    amazon_transactions_client.get_transactions.return_value = [
        _amazon_txn("111-1111111", -259.90, date(2026, 6, 1)),
    ]
    amazon_orders_client = mocker.Mock()

    result = find_amazon_transactions(
        ynab_client,
        amazon_transactions_client,
        lambda: amazon_orders_client,
        "budget-1",
    )

    assert result["matches"] == []
    assert result["ambiguous"] == []
    assert result["unmatched"] == []
    amazon_orders_client.get_order.assert_not_called()


def test_find_amazon_transactions_includes_approved_when_requested(
    mocker: MockerFixture,
) -> None:
    """include_approved=True opts back into matching approved transactions."""
    ynab_client = mocker.Mock()
    list_transactions = mocker.patch(
        "ynab_mcp.tools.find_amazon_transactions.list_transactions"
    )
    list_transactions.return_value = [
        _ynab_txn(mocker, "y1", -259900, date(2026, 6, 1), "Amazon.com", approved=True),
    ]
    amazon_transactions_client = mocker.Mock()
    amazon_transactions_client.get_transactions.return_value = [
        _amazon_txn("111-1111111", -259.90, date(2026, 6, 1)),
    ]
    amazon_orders_client = mocker.Mock()
    amazon_orders_client.get_order.return_value = _order(["Widget"])

    result = find_amazon_transactions(
        ynab_client,
        amazon_transactions_client,
        lambda: amazon_orders_client,
        "budget-1",
        include_approved=True,
    )

    assert len(result["matches"]) == 1  # type: ignore[arg-type]


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
            ynab_client,
            amazon_transactions_client,
            lambda: amazon_orders_client,
            "budget-1",
        )


def test_find_amazon_transactions_attributes_enrichment_to_correct_order(
    mocker: MockerFixture,
) -> None:
    """Each match's enrichment reflects its own order, never a neighbor's.

    A single shared mock client is sufficient here: attribution
    correctness comes from the order_futures dict keying in the
    implementation, not from which physical client served a request.
    """
    ynab_client = mocker.Mock()
    list_transactions = mocker.patch(
        "ynab_mcp.tools.find_amazon_transactions.list_transactions"
    )
    list_transactions.return_value = [
        _ynab_txn(mocker, "y1", -10000, date(2026, 6, 1), "Amazon.com"),
        _ynab_txn(mocker, "y2", -20000, date(2026, 6, 2), "Amazon.com"),
    ]
    amazon_transactions_client = mocker.Mock()
    amazon_transactions_client.get_transactions.return_value = [
        _amazon_txn("111-1111111", -10.00, date(2026, 6, 1)),
        _amazon_txn("222-2222222", -20.00, date(2026, 6, 2)),
    ]
    orders_by_number = {
        "111-1111111": _order(["First Widget"]),
        "222-2222222": _order(["Second Widget"]),
    }
    shared_client = mocker.Mock()
    shared_client.get_order.side_effect = lambda order_number: orders_by_number[
        order_number
    ]

    result = find_amazon_transactions(
        ynab_client,
        amazon_transactions_client,
        lambda: shared_client,
        "budget-1",
    )

    matches_by_order = {m["order_number"]: m for m in result["matches"]}  # type: ignore[attr-defined]
    assert "First Widget" in matches_by_order["111-1111111"]["reasoning"]
    assert "Second Widget" in matches_by_order["222-2222222"]["reasoning"]


def test_find_amazon_transactions_fetches_orders_concurrently(
    mocker: MockerFixture,
) -> None:
    """At least two order fetches are genuinely in flight at the same time.

    A threading.Barrier forces two fetches to rendezvous before either can
    proceed -- deterministic proof of real concurrency, not a timing
    threshold (which would be flaky under CI load variance). If the
    fetches ran sequentially, the second call would never reach the
    barrier while the first is waiting, and the test would hang until
    pytest's timeout.
    """
    ynab_client = mocker.Mock()
    list_transactions = mocker.patch(
        "ynab_mcp.tools.find_amazon_transactions.list_transactions"
    )
    list_transactions.return_value = [
        _ynab_txn(mocker, "y1", -10000, date(2026, 6, 1), "Amazon.com"),
        _ynab_txn(mocker, "y2", -20000, date(2026, 6, 2), "Amazon.com"),
    ]
    amazon_transactions_client = mocker.Mock()
    amazon_transactions_client.get_transactions.return_value = [
        _amazon_txn("111-1111111", -10.00, date(2026, 6, 1)),
        _amazon_txn("222-2222222", -20.00, date(2026, 6, 2)),
    ]
    barrier = threading.Barrier(2, timeout=5)

    def _get_order(order_number: str) -> SimpleNamespace:
        barrier.wait()
        return _order(["Widget"])

    shared_client = mocker.Mock()
    shared_client.get_order.side_effect = _get_order

    result = find_amazon_transactions(
        ynab_client,
        amazon_transactions_client,
        lambda: shared_client,
        "budget-1",
    )

    assert len(result["matches"]) == 2  # type: ignore[arg-type]


def test_find_amazon_transactions_one_order_failure_aborts_cleanly(
    mocker: MockerFixture,
) -> None:
    """One failing order fetch aborts the whole call, matching today's behavior."""
    ynab_client = mocker.Mock()
    list_transactions = mocker.patch(
        "ynab_mcp.tools.find_amazon_transactions.list_transactions"
    )
    list_transactions.return_value = [
        _ynab_txn(mocker, "y1", -10000, date(2026, 6, 1), "Amazon.com"),
        _ynab_txn(mocker, "y2", -20000, date(2026, 6, 2), "Amazon.com"),
    ]
    amazon_transactions_client = mocker.Mock()
    amazon_transactions_client.get_transactions.return_value = [
        _amazon_txn("111-1111111", -10.00, date(2026, 6, 1)),
        _amazon_txn("222-2222222", -20.00, date(2026, 6, 2)),
    ]

    def _get_order(order_number: str) -> SimpleNamespace:
        if order_number == "222-2222222":
            raise AmazonOrdersAuthError("expired mid-run")
        return _order(["Widget"])

    shared_client = mocker.Mock()
    shared_client.get_order.side_effect = _get_order

    with raises(ToolError, match="scripts/amazon_login.py"):
        find_amazon_transactions(
            ynab_client,
            amazon_transactions_client,
            lambda: shared_client,
            "budget-1",
        )


def test_find_amazon_transactions_reuses_worker_sessions_across_orders(
    mocker: MockerFixture,
) -> None:
    """The factory is called at most once per worker thread, not once per order.

    10 distinct orders with a 3-worker pool should call the factory at
    most 3 times -- proving sessions are built once per worker thread and
    reused, not rebuilt per fetch. Uses an explicit lock-guarded counter
    rather than Mock.call_count, since Mock's internal call-tracking isn't
    guaranteed thread-safe under concurrent invocation from multiple
    worker threads.
    """
    ynab_client = mocker.Mock()
    list_transactions = mocker.patch(
        "ynab_mcp.tools.find_amazon_transactions.list_transactions"
    )
    list_transactions.return_value = [
        _ynab_txn(mocker, f"y{i}", -10000 * i, date(2026, 6, i), "Amazon.com")
        for i in range(1, 11)
    ]
    amazon_transactions_client = mocker.Mock()
    amazon_transactions_client.get_transactions.return_value = [
        _amazon_txn(f"11{i}-1111111", -10.00 * i, date(2026, 6, i))
        for i in range(1, 11)
    ]

    call_count_lock = threading.Lock()
    call_count = 0

    def _client_factory() -> Mock:
        nonlocal call_count
        with call_count_lock:
            call_count += 1
        client = mocker.Mock()
        client.get_order.side_effect = lambda order_number: _order(["Widget"])
        return client

    result = find_amazon_transactions(
        ynab_client,
        amazon_transactions_client,
        _client_factory,
        "budget-1",
    )

    assert len(result["matches"]) == 10  # type: ignore[arg-type]
    assert call_count <= 3
