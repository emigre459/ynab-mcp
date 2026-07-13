"""find-payee-transactions tool: locate a payee's transaction patterns."""

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

import ynab

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
