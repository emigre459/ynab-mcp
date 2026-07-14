"""Tests for ynab_mcp.amazon_matching."""

from datetime import date

from ynab_mcp.amazon_matching import (
    AmazonCandidate,
    YnabCandidate,
    match_transactions,
)


def test_exact_same_day_amount_and_date_match() -> None:
    """A single Amazon transaction with the same amount and date is exact."""
    ynab_txns = [YnabCandidate("y1", -25990, date(2026, 6, 1))]
    amazon_txns = [AmazonCandidate("a1:0", "111-1111111", -25990, date(2026, 6, 1))]

    result = match_transactions(ynab_txns, amazon_txns)

    assert len(result.matches) == 1
    match = result.matches[0]
    assert match.ynab_transaction_id == "y1"
    assert match.amazon_transaction_ref == "a1:0"
    assert match.order_number == "111-1111111"
    assert match.classification == "exact"
    assert match.same_day is True
    assert match.split_group == []
    assert result.ambiguous == []
    assert result.unmatched == []


def test_near_date_match_within_window_but_not_same_day() -> None:
    """A same-amount match a few days off (within the window) is near-date."""
    ynab_txns = [YnabCandidate("y1", -10000, date(2026, 6, 5))]
    amazon_txns = [AmazonCandidate("a1:0", "111-2222222", -10000, date(2026, 6, 3))]

    result = match_transactions(ynab_txns, amazon_txns, date_window_days=3)

    assert len(result.matches) == 1
    assert result.matches[0].classification == "near-date"
    assert result.matches[0].same_day is False


def test_date_outside_window_is_no_match() -> None:
    """A same-amount charge outside the date window doesn't count."""
    ynab_txns = [YnabCandidate("y1", -10000, date(2026, 6, 10))]
    amazon_txns = [AmazonCandidate("a1:0", "111-3333333", -10000, date(2026, 6, 1))]

    result = match_transactions(ynab_txns, amazon_txns, date_window_days=3)

    assert result.matches == []
    assert result.unmatched == ["y1"]


def test_split_shipment_groups_multiple_legs_of_one_order() -> None:
    """Two YNAB transactions each uniquely matching legs of one order group."""
    ynab_txns = [
        YnabCandidate("y1", -5000, date(2026, 6, 1)),
        YnabCandidate("y2", -7500, date(2026, 6, 2)),
    ]
    amazon_txns = [
        AmazonCandidate("a1:0", "222-0000000", -5000, date(2026, 6, 1)),
        AmazonCandidate("a1:1", "222-0000000", -7500, date(2026, 6, 2)),
    ]

    result = match_transactions(ynab_txns, amazon_txns)

    assert len(result.matches) == 2
    by_id = {m.ynab_transaction_id: m for m in result.matches}
    assert by_id["y1"].classification == "split-shipment"
    assert by_id["y2"].classification == "split-shipment"
    assert by_id["y1"].split_group == ["y2"]
    assert by_id["y2"].split_group == ["y1"]
    assert result.ambiguous == []
    assert result.unmatched == []


def test_ambiguous_when_two_amazon_candidates_tie_for_one_ynab_transaction() -> None:
    """Two equally-good Amazon candidates for one YNAB transaction are ambiguous."""
    ynab_txns = [YnabCandidate("y1", -3000, date(2026, 6, 5))]
    amazon_txns = [
        AmazonCandidate("a1:0", "333-1111111", -3000, date(2026, 6, 4)),
        AmazonCandidate("a2:0", "333-2222222", -3000, date(2026, 6, 6)),
    ]

    result = match_transactions(ynab_txns, amazon_txns, date_window_days=3)

    assert result.matches == []
    assert len(result.ambiguous) == 1
    ambiguous = result.ambiguous[0]
    assert ambiguous.ynab_transaction_id == "y1"
    assert set(ambiguous.candidate_refs) == {"a1:0", "a2:0"}
    assert result.unmatched == []


def test_ambiguous_when_one_amazon_candidate_ties_between_two_ynab_transactions() -> (
    None
):
    """One Amazon candidate tying between two YNAB transactions is ambiguous for both."""
    ynab_txns = [
        YnabCandidate("y1", -4000, date(2026, 6, 5)),
        YnabCandidate("y2", -4000, date(2026, 6, 5)),
    ]
    amazon_txns = [AmazonCandidate("a1:0", "444-1111111", -4000, date(2026, 6, 5))]

    result = match_transactions(ynab_txns, amazon_txns)

    assert result.matches == []
    assert len(result.ambiguous) == 2
    ynab_ids = {a.ynab_transaction_id for a in result.ambiguous}
    assert ynab_ids == {"y1", "y2"}
    for ambiguous in result.ambiguous:
        assert ambiguous.candidate_refs == ["a1:0"]


def test_no_match_when_no_amazon_candidate_in_range() -> None:
    """An Amazon-like YNAB transaction with nothing nearby is unmatched."""
    ynab_txns = [YnabCandidate("y1", -9999, date(2026, 6, 1))]
    amazon_txns: list[AmazonCandidate] = []

    result = match_transactions(ynab_txns, amazon_txns)

    assert result.matches == []
    assert result.ambiguous == []
    assert result.unmatched == ["y1"]
