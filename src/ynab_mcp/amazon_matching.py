"""Pure merge-key algorithm joining YNAB transactions to Amazon charges.

No I/O and no dependency on the ``ynab`` or ``amazon-orders`` SDKs -- both
sides are pre-converted by the caller into the small dataclasses below, so
this module is fully testable with plain fixtures.
"""

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class YnabCandidate:
    """A YNAB transaction being considered for an Amazon match.

    Parameters
    ----------
    transaction_id : str
        The YNAB transaction's id.
    amount : int
        The transaction amount in milliunits (negative for outflows),
        matching YNAB's own sign convention.
    txn_date : datetime.date
        The transaction's date.
    """

    transaction_id: str
    amount: int
    txn_date: date


@dataclass(frozen=True)
class AmazonCandidate:
    """An Amazon charge/refund record being considered for a YNAB match.

    Parameters
    ----------
    transaction_ref : str
        A caller-assigned unique identifier for this specific Amazon
        transaction record -- distinct even when two shipments of the same
        order tie on amount and date.
    order_number : str
        The Amazon order this charge belongs to. Multiple
        ``AmazonCandidate``s can share an ``order_number`` for
        split-shipment orders.
    amount : int
        The charge amount in milliunits, sign-aligned with
        ``YnabCandidate.amount`` (negative, since it's an outflow).
    txn_date : datetime.date
        The date the charge completed.
    """

    transaction_ref: str
    order_number: str
    amount: int
    txn_date: date


@dataclass(frozen=True)
class Match:
    """A confident, uniquely-resolved match between one YNAB and one Amazon transaction.

    Parameters
    ----------
    ynab_transaction_id : str
        The matched YNAB transaction's id.
    amazon_transaction_ref : str
        The matched Amazon transaction's ``transaction_ref``.
    order_number : str
        The Amazon order this charge belongs to.
    classification : {"exact", "near-date", "split-shipment"}
        How confident the match is.
    same_day : bool
        Whether the YNAB and Amazon dates were identical.
    split_group : list[str]
        Sibling YNAB transaction ids sharing this ``order_number``, when
        ``classification`` is ``"split-shipment"``; empty otherwise.
    """

    ynab_transaction_id: str
    amazon_transaction_ref: str
    order_number: str
    classification: str
    same_day: bool
    split_group: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AmbiguousMatch:
    """A YNAB transaction with more than one equally-good Amazon candidate.

    Parameters
    ----------
    ynab_transaction_id : str
        The ambiguous YNAB transaction's id.
    candidate_refs : list[str]
        The tied Amazon transactions' ``transaction_ref`` values.
    """

    ynab_transaction_id: str
    candidate_refs: list[str]


@dataclass(frozen=True)
class MatchResult:
    """The full output of :func:`match_transactions`.

    Parameters
    ----------
    matches : list[Match]
        Confidently, uniquely resolved matches.
    ambiguous : list[AmbiguousMatch]
        YNAB transactions with multiple tied Amazon candidates (or vice
        versa), surfaced for a human to disambiguate rather than guessed.
    unmatched : list[str]
        YNAB transaction ids with no Amazon candidate in range.
    """

    matches: list[Match]
    ambiguous: list[AmbiguousMatch]
    unmatched: list[str]


def match_transactions(
    ynab_transactions: list[YnabCandidate],
    amazon_transactions: list[AmazonCandidate],
    date_window_days: int = 3,
) -> MatchResult:
    """Join YNAB transactions to Amazon charges on exact amount + date window.

    Two passes: pass 1 buckets each YNAB transaction by how many Amazon
    candidates tie for it (and vice versa) into ``no-match`` / ``ambiguous``
    / a uniquely-resolved pair. Pass 2 regroups uniquely-resolved pairs by
    ``order_number``: any order with more than one resolved leg is a
    split-shipment order, and every leg's classification becomes
    ``"split-shipment"``.

    Parameters
    ----------
    ynab_transactions : list[YnabCandidate]
        Candidate YNAB transactions (already pre-filtered to Amazon-like
        payees by the caller).
    amazon_transactions : list[AmazonCandidate]
        Candidate Amazon transactions (already pre-filtered to exclude
        refunds/Whole Foods by the caller).
    date_window_days : int, optional
        Maximum number of days apart (inclusive, either direction) a YNAB
        and Amazon date may be and still count as a match, by default
        ``3``.

    Returns
    -------
    MatchResult
        The classified matches, ambiguous ties, and unmatched transactions.
    """
    ynab_to_amazon: dict[str, list[AmazonCandidate]] = {}
    amazon_to_ynab: dict[str, list[str]] = {}
    for ynab_txn in ynab_transactions:
        candidates = [
            amazon_txn
            for amazon_txn in amazon_transactions
            if amazon_txn.amount == ynab_txn.amount
            and abs((amazon_txn.txn_date - ynab_txn.txn_date).days) <= date_window_days
        ]
        ynab_to_amazon[ynab_txn.transaction_id] = candidates
        for amazon_txn in candidates:
            amazon_to_ynab.setdefault(amazon_txn.transaction_ref, []).append(
                ynab_txn.transaction_id
            )

    ambiguous: list[AmbiguousMatch] = []
    unmatched: list[str] = []
    unique_pairs: list[tuple[YnabCandidate, AmazonCandidate]] = []

    for ynab_txn in ynab_transactions:
        candidates = ynab_to_amazon[ynab_txn.transaction_id]
        if not candidates:
            unmatched.append(ynab_txn.transaction_id)
        elif len(candidates) > 1:
            ambiguous.append(
                AmbiguousMatch(
                    ynab_transaction_id=ynab_txn.transaction_id,
                    candidate_refs=[c.transaction_ref for c in candidates],
                )
            )
        else:
            candidate = candidates[0]
            if len(amazon_to_ynab[candidate.transaction_ref]) > 1:
                ambiguous.append(
                    AmbiguousMatch(
                        ynab_transaction_id=ynab_txn.transaction_id,
                        candidate_refs=[candidate.transaction_ref],
                    )
                )
            else:
                unique_pairs.append((ynab_txn, candidate))

    groups: dict[str, list[tuple[YnabCandidate, AmazonCandidate]]] = {}
    for ynab_txn, amazon_txn in unique_pairs:
        groups.setdefault(amazon_txn.order_number, []).append((ynab_txn, amazon_txn))

    matches: list[Match] = []
    for order_number, pairs in groups.items():
        is_split = len(pairs) > 1
        for ynab_txn, amazon_txn in pairs:
            same_day = ynab_txn.txn_date == amazon_txn.txn_date
            classification = (
                "split-shipment" if is_split else ("exact" if same_day else "near-date")
            )
            matches.append(
                Match(
                    ynab_transaction_id=ynab_txn.transaction_id,
                    amazon_transaction_ref=amazon_txn.transaction_ref,
                    order_number=order_number,
                    classification=classification,
                    same_day=same_day,
                    split_group=(
                        [
                            other.transaction_id
                            for other, _ in pairs
                            if other.transaction_id != ynab_txn.transaction_id
                        ]
                        if is_split
                        else []
                    ),
                )
            )

    # Preserve input ordering for deterministic, readable output.
    order_index = {t.transaction_id: i for i, t in enumerate(ynab_transactions)}
    matches.sort(key=lambda m: order_index[m.ynab_transaction_id])
    ambiguous.sort(key=lambda a: order_index[a.ynab_transaction_id])
    unmatched.sort(key=lambda tid: order_index[tid])

    return MatchResult(matches=matches, ambiguous=ambiguous, unmatched=unmatched)
