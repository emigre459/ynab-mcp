"""Tests for ynab_mcp.tools.payee_patterns."""

from types import SimpleNamespace

from ynab_mcp.tools.payee_patterns import _match_payees


def test_match_payees_exact_match() -> None:
    """A payee name equal to the query (case-insensitive) matches exactly."""
    payees = [
        SimpleNamespace(id="p1", name="Amazon.com"),
        SimpleNamespace(id="p2", name="Starbucks"),
    ]

    matches = _match_payees(payees, "amazon.com", fuzzy_threshold=0.6)  # type: ignore[arg-type]

    assert len(matches) == 1
    assert matches[0].payee.id == "p1"
    assert matches[0].match_type == "exact"
    assert matches[0].match_score is None


def test_match_payees_substring_match() -> None:
    """A query that is a substring of the payee name matches by substring."""
    payees = [SimpleNamespace(id="p1", name="AMZN Mktp US Amazon")]

    matches = _match_payees(payees, "amazon", fuzzy_threshold=0.6)  # type: ignore[arg-type]

    assert len(matches) == 1
    assert matches[0].match_type == "substring"
    assert matches[0].match_score is None


def test_match_payees_fuzzy_match() -> None:
    """A payee name that doesn't literally contain the query still matches.

    It matches by fuzzy similarity when its score is above the threshold.
    """
    payees = [SimpleNamespace(id="p1", name="Wal-Mart #1234")]

    matches = _match_payees(payees, "walmart", fuzzy_threshold=0.6)  # type: ignore[arg-type]

    assert len(matches) == 1
    assert matches[0].match_type == "fuzzy"
    assert matches[0].match_score is not None
    assert matches[0].match_score >= 0.6


def test_match_payees_no_match() -> None:
    """A payee name that doesn't match at all is excluded entirely.

    It scores below the fuzzy threshold and doesn't contain the query.
    """
    payees = [SimpleNamespace(id="p1", name="Netflix")]

    matches = _match_payees(payees, "walmart", fuzzy_threshold=0.6)  # type: ignore[arg-type]

    assert matches == []
