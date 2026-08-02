"""find-payee-transactions tool: locate a payee's transaction patterns."""

import statistics
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from difflib import SequenceMatcher
from typing import Literal

import ynab
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from ynab_mcp.client import resolve_budget_id
from ynab_mcp.config import Settings
from ynab_mcp.tools.payees import list_payees
from ynab_mcp.tools.transactions import list_transactions

MatchType = Literal["exact", "substring", "fuzzy"]


@dataclass(frozen=True)
class _MatchedPayee:
    """A payee that matched a lookup query, and how it matched.

    Parameters
    ----------
    payee : ynab.Payee
        The matched payee record.
    match_type : MatchType
        Whether the match was exact, substring, or fuzzy.
    match_score : float | None
        The ``difflib`` similarity ratio, set only when ``match_type`` is
        ``"fuzzy"``.
    """

    payee: ynab.Payee
    match_type: MatchType
    match_score: float | None


def _match_payees(
    payees: list[ynab.Payee], payee_query: str, fuzzy_threshold: float
) -> list[_MatchedPayee]:
    """Match payees against a query, case-insensitively.

    Checks each payee name for an exact match, then a substring match in
    either direction, then falls back to a ``difflib`` similarity ratio
    for names that don't literally contain the query -- catching
    abbreviations like "AMZN Mktp US" for a search on "amazon" that a
    plain substring check would miss.

    Parameters
    ----------
    payees : list[ynab.Payee]
        Every payee in the budget.
    payee_query : str
        The caller's search term.
    fuzzy_threshold : float
        The minimum ``difflib.SequenceMatcher.ratio()`` for a name that
        doesn't contain the query to still count as a match.

    Returns
    -------
    list[_MatchedPayee]
        Every payee that matched, in payee order.
    """
    query = payee_query.strip().lower()
    matches: list[_MatchedPayee] = []
    for payee in payees:
        name = payee.name.lower()
        if name == query:
            matches.append(_MatchedPayee(payee, "exact", None))
        elif query in name or name in query:
            matches.append(_MatchedPayee(payee, "substring", None))
        else:
            score = SequenceMatcher(None, query, name).ratio()
            if score >= fuzzy_threshold:
                matches.append(_MatchedPayee(payee, "fuzzy", score))
    return matches


_RECURRING_MIN_COUNT = 3
_RECURRING_TOLERANCE_FRACTION = 0.1
_RECURRING_TOLERANCE_FLOOR_MILLIUNITS = 1000


@dataclass(frozen=True)
class AmountRange:
    """The minimum and maximum transaction amount in a group, in milliunits.

    Parameters
    ----------
    min : int
        The smallest transaction amount.
    max : int
        The largest transaction amount.
    """

    min: int
    max: int


@dataclass(frozen=True)
class PayeeGroupSummary:
    """Transaction-pattern statistics for one matched payee.

    Parameters
    ----------
    payee_id : str
        The matched YNAB payee id.
    payee_name : str
        The matched YNAB payee name.
    match_type : MatchType
        How this payee matched the caller's query.
    match_score : float | None
        The ``difflib`` similarity ratio, set only when ``match_type`` is
        ``"fuzzy"``.
    transaction_count : int
        Number of transactions for this payee.
    typical_amount : int
        Median transaction amount, in milliunits.
    amount_range : AmountRange
        The min/max transaction amount, in milliunits.
    most_common_category : str | None
        The mode of ``category_name`` across the group's transactions, or
        ``None`` if none are categorized.
    recurring_guess : str | None
        A human-readable recurring-charge guess when the heuristic fires,
        otherwise ``None``.
    """

    payee_id: str
    payee_name: str
    match_type: MatchType
    match_score: float | None
    transaction_count: int
    typical_amount: int
    amount_range: AmountRange
    most_common_category: str | None
    recurring_guess: str | None


def _most_common_category(transactions: list[ynab.TransactionDetail]) -> str | None:
    """Find the most frequent category name among a group's transactions.

    A split transaction's own ``category_name`` is always the literal
    string ``"Split"`` (never a real category) -- its subtransactions
    carry the actual per-line-item categories, so those are counted
    instead of the parent's "Split" placeholder.

    Parameters
    ----------
    transactions : list[ynab.TransactionDetail]
        The matched payee's transactions.

    Returns
    -------
    str | None
        The most common category name, or ``None`` if no transaction (or
        subtransaction, for splits) has a category.
    """
    categories: list[str] = []
    for transaction in transactions:
        if transaction.category_name == "Split":
            categories.extend(
                sub.category_name
                for sub in transaction.subtransactions
                if sub.category_name
            )
        elif transaction.category_name:
            categories.append(transaction.category_name)
    if not categories:
        return None
    return Counter(categories).most_common(1)[0][0]


def _recurring_guess(amounts: list[int], typical_amount: int) -> str | None:
    """Guess whether a group of amounts represents a recurring charge.

    Fires when there are at least ``_RECURRING_MIN_COUNT`` transactions
    and every amount falls within a tolerance band of the median -- the
    greater of ``_RECURRING_TOLERANCE_FRACTION`` of the median or
    ``_RECURRING_TOLERANCE_FLOOR_MILLIUNITS``, so cheap recurring charges
    aren't missed by a purely percentage-based tolerance.

    Parameters
    ----------
    amounts : list[int]
        Every transaction amount in the group, in milliunits.
    typical_amount : int
        The group's median amount, in milliunits.

    Returns
    -------
    str | None
        A human-readable guess, or ``None`` if the heuristic doesn't fire.
    """
    if len(amounts) < _RECURRING_MIN_COUNT:
        return None
    tolerance = max(
        abs(typical_amount) * _RECURRING_TOLERANCE_FRACTION,
        _RECURRING_TOLERANCE_FLOOR_MILLIUNITS,
    )
    if not all(abs(amount - typical_amount) <= tolerance for amount in amounts):
        return None
    dollars = abs(typical_amount) / 1000
    return f"Looks like a recurring charge (~${dollars:.2f}, seen {len(amounts)} times)"


def _summarize_group(
    matched: _MatchedPayee, transactions: list[ynab.TransactionDetail]
) -> PayeeGroupSummary:
    """Compute transaction-pattern statistics for one matched payee.

    Parameters
    ----------
    matched : _MatchedPayee
        The payee this group belongs to, and how it matched.
    transactions : list[ynab.TransactionDetail]
        The matched payee's transactions. Must be non-empty.

    Returns
    -------
    PayeeGroupSummary
        The computed statistics for this payee's transactions.
    """
    amounts = [t.amount for t in transactions]
    typical_amount = round(statistics.median(amounts))
    return PayeeGroupSummary(
        payee_id=str(matched.payee.id),
        payee_name=matched.payee.name,
        match_type=matched.match_type,
        match_score=matched.match_score,
        transaction_count=len(transactions),
        typical_amount=typical_amount,
        amount_range=AmountRange(min=min(amounts), max=max(amounts)),
        most_common_category=_most_common_category(transactions),
        recurring_guess=_recurring_guess(amounts, typical_amount),
    )


def find_payee_transactions(
    client: ynab.ApiClient,
    budget_id: str,
    payee_query: str,
    fuzzy_threshold: float = 0.6,
    since_date: date | None = None,
    until_date: date | None = None,
) -> list[PayeeGroupSummary]:
    """Find transaction patterns for payees matching a query.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id (translated to the SDK's ``plan_id``).
    payee_query : str
        A payee name or substring to search for.
    fuzzy_threshold : float, optional
        The minimum ``difflib`` similarity ratio for a non-substring
        match, by default ``0.6``.
    since_date : datetime.date | None, optional
        Only consider transactions on or after this date, by default
        ``None`` (YNAB's own API defaults to one year ago).
    until_date : datetime.date | None, optional
        Only consider transactions on or before this date, by default
        ``None``.

    Returns
    -------
    list[PayeeGroupSummary]
        One summary per matched payee with at least one transaction.
        Empty if no payee matches ``payee_query``.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If ``payee_query`` is empty or whitespace-only, or if an
        underlying YNAB API request fails.
    """
    if not payee_query.strip():
        raise ToolError("payee_query must not be empty.")

    payees = list_payees(client, budget_id)
    matches = _match_payees(payees, payee_query, fuzzy_threshold)
    if not matches:
        return []

    all_transactions = list_transactions(
        client, budget_id, since_date=since_date, until_date=until_date
    )
    transactions_by_payee_id: dict[str, list[ynab.TransactionDetail]] = defaultdict(
        list
    )
    for transaction in all_transactions:
        if transaction.payee_id is not None:
            transactions_by_payee_id[str(transaction.payee_id)].append(transaction)

    summaries: list[PayeeGroupSummary] = []
    for matched in matches:
        transactions = transactions_by_payee_id.get(str(matched.payee.id), [])
        if not transactions:
            continue
        summaries.append(_summarize_group(matched, transactions))
    return summaries


def register(mcp: FastMCP, client: ynab.ApiClient, settings: Settings) -> None:
    """Register the ``find-payee-transactions`` tool on ``mcp``.

    Parameters
    ----------
    mcp : fastmcp.FastMCP
        The server to register the tool on.
    client : ynab.ApiClient
        A configured YNAB API client.
    settings : Settings
        The server's parsed configuration, used to resolve a default
        budget id when the caller omits one.
    """

    @mcp.tool(name="find-payee-transactions")
    def find_payee_transactions_tool(
        payee_query: str,
        budget_id: str | None = None,
        since_date: date | None = None,
        until_date: date | None = None,
    ) -> list[dict[str, object]]:
        """Find transaction patterns for payees matching a query.

        Parameters
        ----------
        payee_query : str
            A payee name or substring to search for.
        budget_id : str | None, optional
            The YNAB budget id, by default ``None`` (falls back to
            ``YNAB_DEFAULT_BUDGET_ID``).
        since_date : datetime.date | None, optional
            Only consider transactions on or after this date, by default
            ``None`` (YNAB's own API defaults to one year ago).
        until_date : datetime.date | None, optional
            Only consider transactions on or before this date, by default
            ``None``.
        """
        resolved_budget_id = resolve_budget_id(budget_id, settings)
        summaries = find_payee_transactions(
            client,
            resolved_budget_id,
            payee_query,
            since_date=since_date,
            until_date=until_date,
        )
        return [asdict(summary) for summary in summaries]
