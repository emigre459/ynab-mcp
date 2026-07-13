"""find-amazon-transactions tool: match YNAB transactions to Amazon orders."""

from datetime import date

import ynab
from amazonorders.entity.order import Order
from amazonorders.entity.transaction import Transaction
from amazonorders.exception import AmazonOrdersError
from amazonorders.orders import AmazonOrders
from amazonorders.transactions import AmazonTransactions
from fastmcp import FastMCP

from ynab_mcp.amazon_matching import AmazonCandidate, YnabCandidate, match_transactions
from ynab_mcp.client import resolve_budget_id
from ynab_mcp.config import Settings
from ynab_mcp.errors import translate_amazon_exception
from ynab_mcp.tools.transactions import list_transactions

_AMAZON_PAYEE_MARKERS = ("amazon", "amzn")
_WHOLE_FOODS_MARKER = "whole foods"
_DEFAULT_LOOKBACK_DAYS = 365


def _is_amazon_like_payee(payee_name: str | None) -> bool:
    """Return whether a YNAB payee name looks like an Amazon charge."""
    if payee_name is None:
        return False
    lowered = payee_name.lower()
    return any(marker in lowered for marker in _AMAZON_PAYEE_MARKERS)


def _is_whole_foods_transaction(transaction: Transaction) -> bool:
    """Return whether an Amazon transaction is a Whole Foods charge."""
    return _WHOLE_FOODS_MARKER in transaction.seller.lower()


def _amount_to_milliunits(grand_total: float) -> int:
    """Convert an Amazon dollar amount into signed YNAB milliunits.

    Amazon charges are outflows, so the result is negative, matching
    YNAB's sign convention for money leaving an account.
    """
    cents = round(grand_total * 100)
    return -cents * 10


def _lookback_days(since_date: date | None, date_window_days: int) -> int:
    """Compute how many days of Amazon transaction history to fetch."""
    if since_date is None:
        return _DEFAULT_LOOKBACK_DAYS
    elapsed = (date.today() - since_date).days + date_window_days
    return max(elapsed, 1)


def _build_reasoning(
    classification: str,
    order_number: str,
    order: Order | None,
    date_window_days: int,
) -> str:
    """Build a human-readable reasoning string for a match."""
    item_titles = ", ".join(item.title for item in order.items[:3]) if order else ""
    suffix = f" ({item_titles})" if item_titles else ""
    if classification == "exact":
        return f"Exact amount+date match against Amazon order #{order_number}{suffix}."
    if classification == "near-date":
        return (
            f"Amount match against Amazon order #{order_number} within "
            f"{date_window_days} days{suffix}."
        )
    return f"One leg of a split-shipment Amazon order #{order_number}{suffix}."


def _serialize_amazon_transaction(transaction: Transaction) -> dict[str, object]:
    """Serialize an Amazon transaction into a JSON-safe dict."""
    return {
        "order_number": transaction.order_number,
        "completed_date": transaction.completed_date.isoformat(),
        "grand_total": transaction.grand_total,
        "payment_method": transaction.payment_method,
        "seller": transaction.seller,
        "is_refund": transaction.is_refund,
    }


def find_amazon_transactions(
    ynab_client: ynab.ApiClient,
    amazon_transactions_client: AmazonTransactions,
    amazon_orders_client: AmazonOrders,
    budget_id: str,
    since_date: date | None = None,
    until_date: date | None = None,
    date_window_days: int = 3,
) -> dict[str, object]:
    """Match YNAB transactions against Amazon order/transaction history.

    Parameters
    ----------
    ynab_client : ynab.ApiClient
        A configured YNAB API client.
    amazon_transactions_client : amazonorders.transactions.AmazonTransactions
        A configured Amazon transactions client.
    amazon_orders_client : amazonorders.orders.AmazonOrders
        A configured Amazon orders client, used to enrich matches with
        item-level detail.
    budget_id : str
        The YNAB budget id.
    since_date : datetime.date | None, optional
        Only consider YNAB transactions on or after this date, by default
        ``None``.
    until_date : datetime.date | None, optional
        Only consider YNAB transactions on or before this date, by default
        ``None``.
    date_window_days : int, optional
        Maximum number of days apart a YNAB and Amazon date may be and
        still count as a match, by default ``3``.

    Returns
    -------
    dict[str, object]
        ``{"matches": [...], "ambiguous": [...], "unmatched": [...]}``. No
        categorization is written back to YNAB -- this tool only proposes.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If the Amazon session is missing/expired or another
        ``amazon-orders`` request fails, or if the YNAB API request fails.
    """
    ynab_transactions = list_transactions(
        ynab_client, budget_id, since_date=since_date, until_date=until_date
    )
    amazon_like_txns = [
        t for t in ynab_transactions if _is_amazon_like_payee(t.payee_name)
    ]
    ynab_by_id = {t.id: t for t in amazon_like_txns}
    ynab_candidates = [
        YnabCandidate(transaction_id=t.id, amount=t.amount, txn_date=t.var_date)
        for t in amazon_like_txns
    ]

    try:
        raw_amazon_transactions = amazon_transactions_client.get_transactions(
            days=_lookback_days(since_date, date_window_days)
        )
    except AmazonOrdersError as exc:
        raise translate_amazon_exception(exc) from exc

    filtered_amazon_transactions = [
        t
        for t in raw_amazon_transactions
        if not t.is_refund and not _is_whole_foods_transaction(t)
    ]
    amazon_by_ref = {
        f"{t.order_number}:{i}": t for i, t in enumerate(filtered_amazon_transactions)
    }
    amazon_candidates = [
        AmazonCandidate(
            transaction_ref=ref,
            order_number=t.order_number,
            amount=_amount_to_milliunits(t.grand_total),
            txn_date=t.completed_date,
        )
        for ref, t in amazon_by_ref.items()
    ]

    result = match_transactions(ynab_candidates, amazon_candidates, date_window_days)

    orders_cache: dict[str, Order] = {}

    def _order_for(order_number: str) -> Order:
        if order_number not in orders_cache:
            try:
                orders_cache[order_number] = amazon_orders_client.get_order(
                    order_number
                )
            except AmazonOrdersError as exc:
                raise translate_amazon_exception(exc) from exc
        return orders_cache[order_number]

    matches_out: list[dict[str, object]] = []
    for match in result.matches:
        order = _order_for(match.order_number)
        matches_out.append(
            {
                "ynab_transaction": ynab_by_id[match.ynab_transaction_id].model_dump(
                    mode="json"
                ),
                "amazon_transaction": _serialize_amazon_transaction(
                    amazon_by_ref[match.amazon_transaction_ref]
                ),
                "order_number": match.order_number,
                "classification": match.classification,
                "reasoning": _build_reasoning(
                    match.classification, match.order_number, order, date_window_days
                ),
                "split_group": match.split_group,
            }
        )

    ambiguous_out: list[dict[str, object]] = []
    for ambiguous in result.ambiguous:
        candidates_out = [
            {
                "amazon_transaction": _serialize_amazon_transaction(amazon_by_ref[ref]),
                "order_number": amazon_by_ref[ref].order_number,
            }
            for ref in ambiguous.candidate_refs
        ]
        ambiguous_out.append(
            {
                "ynab_transaction": ynab_by_id[
                    ambiguous.ynab_transaction_id
                ].model_dump(mode="json"),
                "candidates": candidates_out,
                "reasoning": (
                    f"{len(candidates_out)} Amazon transaction(s) tie for this "
                    "amount within the date window."
                ),
            }
        )

    unmatched_out: list[dict[str, object]] = []
    for transaction_id in result.unmatched:
        unmatched_out.append(
            {
                "ynab_transaction": ynab_by_id[transaction_id].model_dump(mode="json"),
                "reasoning": "No Amazon transaction found in range.",
            }
        )

    return {
        "matches": matches_out,
        "ambiguous": ambiguous_out,
        "unmatched": unmatched_out,
    }


def register(
    mcp: FastMCP,
    ynab_client: ynab.ApiClient,
    amazon_transactions_client: AmazonTransactions,
    amazon_orders_client: AmazonOrders,
    settings: Settings,
) -> None:
    """Register the ``find-amazon-transactions`` tool on ``mcp``.

    Parameters
    ----------
    mcp : fastmcp.FastMCP
        The server to register the tool on.
    ynab_client : ynab.ApiClient
        A configured YNAB API client.
    amazon_transactions_client : amazonorders.transactions.AmazonTransactions
        A configured Amazon transactions client.
    amazon_orders_client : amazonorders.orders.AmazonOrders
        A configured Amazon orders client.
    settings : Settings
        The server's parsed configuration, used to resolve a default budget
        id when the caller omits one.
    """

    @mcp.tool(name="find-amazon-transactions")
    def find_amazon_transactions_tool(
        budget_id: str | None = None,
        since_date: date | None = None,
        until_date: date | None = None,
        date_window_days: int = 3,
    ) -> dict[str, object]:
        """Match YNAB transactions against Amazon order/transaction history.

        Proposes matches with confidence/reasoning; never writes a
        categorization back to YNAB.

        Parameters
        ----------
        budget_id : str | None, optional
            The YNAB budget id, by default ``None`` (falls back to
            ``YNAB_DEFAULT_BUDGET_ID``).
        since_date : datetime.date | None, optional
            Only consider YNAB transactions on or after this date, by
            default ``None``.
        until_date : datetime.date | None, optional
            Only consider YNAB transactions on or before this date, by
            default ``None``.
        date_window_days : int, optional
            Maximum number of days apart a YNAB and Amazon date may be and
            still count as a match, by default ``3``.
        """
        resolved_budget_id = resolve_budget_id(budget_id, settings)
        return find_amazon_transactions(
            ynab_client,
            amazon_transactions_client,
            amazon_orders_client,
            resolved_budget_id,
            since_date=since_date,
            until_date=until_date,
            date_window_days=date_window_days,
        )
