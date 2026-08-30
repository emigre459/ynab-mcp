"""Pure, zero-I/O reconciliation logic for the ``refresh-accounts`` skill.

Statement parsing and drift computation live here (mirroring ``amazon_matching.py``'s
pure-and-fixture-testable design) so the skill's ``reconcile_report.py`` script can own
the PDF + YNAB I/O and call these functions. Nothing here touches the filesystem, the
network, or the ``ynab`` SDK.

The drift check is deliberately the **anchor-independent monthly-net-diff** method: it
compares the statement's own net change to YNAB's cleared net over the same period, and
the statement's ending balance to YNAB's cleared balance *as of the statement
close date*. It never uses ``current_cleared_balance - Σ(register)``, which is
contaminated by phantom / externally-generated composite-id entries.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime

_MONTHS = {
    m[:3].lower(): i
    for i, m in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        start=1,
    )
}


class StatementParseError(ValueError):
    """Raised when statement text can't be parsed into a :class:`StatementInfo`."""


@dataclass(frozen=True)
class StatementInfo:
    """The facts a reconcile needs from one account's statement period.

    Attributes
    ----------
    bank : str
        ``"chase"`` or ``"ally"``.
    account_tail : str
        The last four of the account number (e.g. ``"0033"``).
    period_start, period_end : datetime.date
        The statement period's inclusive bounds.
    beginning_balance, ending_balance : float
        The statement's opening and closing balances, in dollars.
    """

    bank: str
    account_tail: str
    period_start: date
    period_end: date
    beginning_balance: float
    ending_balance: float

    @property
    def statement_net(self) -> float:
        """The statement's net change over the period (``ending - beginning``)."""
        return round(self.ending_balance - self.beginning_balance, 2)


@dataclass(frozen=True)
class DriftResult:
    """Drift between YNAB and a statement, via the monthly-net-diff method.

    Attributes
    ----------
    statement_net : float
        The statement's ``ending - beginning``.
    activity_drift : float
        ``ynab_net_over_period - statement_net`` — how far YNAB's recorded *activity*
        diverges from the bank's over the same period. Immune to balance-anchor
        contamination.
    balance_drift : float
        ``ynab_cleared_as_of_close - statement_ending`` — how far YNAB's cleared
        balance as of the statement close date sits above (+) or below (-) the
        statement.
    expected_adjustment : float
        The reconciliation adjustment the user should expect (``-balance_drift``): the
        amount to move YNAB by so its cleared balance matches the statement.
    """

    statement_net: float
    activity_drift: float
    balance_drift: float
    expected_adjustment: float


def _money(raw: str) -> float:
    return float(raw.replace(",", ""))


def parse_statement_text(text: str, account_tail: str | None = None) -> StatementInfo:
    """Parse extracted statement text into a :class:`StatementInfo`.

    Parameters
    ----------
    text : str
        The statement's extracted text (e.g. via ``pypdf``).
    account_tail : str, optional
        Required for Ally *combined* statements (multiple accounts in one PDF) to
        pick the right account; ignored for single-account Chase statements.

    Raises
    ------
    StatementParseError
        If the bank can't be detected, the requested account isn't found, an Ally
        statement is ambiguous (multiple accounts, no ``account_tail``), or required
        fields are missing.
    """
    # Detect by which issuer's name dominates. Each bank names itself throughout its own
    # statement (header + every page footer) but mentions the other at most once, in a
    # single transaction line (an Ally statement lists one "JPMORGAN CHASE BANK"
    # transfer; a Chase statement lists one "Ally Bank P2P" deposit) -- so the more
    # frequent issuer wins. Counting names, rather than testing for a ".com" domain
    # substring, both avoids the cross-mention trap and sidesteps the URL-substring
    # anti-pattern.
    lowered = text.lower()
    ally_hits = lowered.count("ally bank")
    chase_hits = lowered.count("jpmorgan chase")
    if ally_hits > chase_hits:
        return _parse_ally(text, account_tail)
    if chase_hits > ally_hits:
        return _parse_chase(text)
    raise StatementParseError("Unrecognized statement format (neither Chase nor Ally).")


def _parse_chase(text: str) -> StatementInfo:
    period = re.search(
        r"([A-Z][a-z]+ \d{1,2}, \d{4})\s+through\s+([A-Z][a-z]+ \d{1,2}, \d{4})", text
    )
    # Chase's PDF text often leaves the "Account Number:" label empty and prints the
    # number as a standalone ~15-digit line that recurs on every page, while a
    # transaction reference number appears once -- so the most frequent 12-17 digit run
    # is the account number. (Anchoring off the label is fragile: its trailing
    # whitespace spans the newline into the next line's transaction ref.)
    runs = re.findall(r"\b(\d{12,17})\b", text)
    account_number = Counter(runs).most_common(1)[0][0] if runs else None
    beg = re.search(r"Beginning Balance\s*\$?([\d,]+\.\d\d)", text)
    end = re.search(r"Ending Balance\s*\$?([\d,]+\.\d\d)", text)
    if not (period and account_number and beg and end):
        raise StatementParseError(
            "Chase statement missing period, account, or balances."
        )
    return StatementInfo(
        bank="chase",
        account_tail=account_number[-4:],
        period_start=datetime.strptime(period.group(1), "%B %d, %Y").date(),
        period_end=datetime.strptime(period.group(2), "%B %d, %Y").date(),
        beginning_balance=_money(beg.group(1)),
        ending_balance=_money(end.group(1)),
    )


def _parse_ally(text: str, account_tail: str | None) -> StatementInfo:
    # Each account's detail block carries its own tail + dated begin/end balances.
    block = re.compile(
        r"Account Number:\s*x*(\d{4}).*?"
        r"Beginning Balance, as of (\d{2}/\d{2}/\d{4})\s*\$?([\d,]+\.\d\d).*?"
        r"Ending Balance, as of (\d{2}/\d{2}/\d{4})\s*\$?([\d,]+\.\d\d)",
        re.DOTALL,
    )
    matches = list(block.finditer(text))
    if not matches:
        raise StatementParseError("Ally statement: no account-detail blocks found.")
    if account_tail is None:
        if len(matches) > 1:
            raise StatementParseError(
                "Ally combined statement has multiple accounts; "
                "account_tail is required."
            )
        m = matches[0]
    else:
        chosen = [m for m in matches if m.group(1) == account_tail]
        if not chosen:
            raise StatementParseError(
                f"Ally statement has no account ending in {account_tail}."
            )
        m = chosen[0]
    return StatementInfo(
        bank="ally",
        account_tail=m.group(1),
        period_start=datetime.strptime(m.group(2), "%m/%d/%Y").date(),
        period_end=datetime.strptime(m.group(4), "%m/%d/%Y").date(),
        beginning_balance=_money(m.group(3)),
        ending_balance=_money(m.group(5)),
    )


def compute_drift(
    statement: StatementInfo,
    ynab_net_over_period: float,
    ynab_cleared_as_of_close: float,
) -> DriftResult:
    """Compute drift via the monthly-net-diff method.

    Parameters
    ----------
    statement : StatementInfo
        The parsed statement.
    ynab_net_over_period : float
        Sum of YNAB *cleared* transaction amounts dated within
        ``[period_start, period_end]``.
    ynab_cleared_as_of_close : float
        YNAB's cleared balance as of ``period_end`` (cleared entries dated on or
        before the close). NOT "now" — using the live balance is what import-lag
        poisons.
    """
    statement_net = statement.statement_net
    balance_drift = round(ynab_cleared_as_of_close - statement.ending_balance, 2)
    return DriftResult(
        statement_net=statement_net,
        activity_drift=round(ynab_net_over_period - statement_net, 2),
        balance_drift=balance_drift,
        expected_adjustment=round(-balance_drift, 2),
    )


def account_drift_from_transactions(
    statement: StatementInfo,
    cleared_transactions: list[tuple[date, float]],
    current_cleared_balance: float,
) -> DriftResult:
    """Compute an account's drift from cleared transactions + current cleared balance.

    Thin, pure adapter over :func:`compute_drift` so the ``reconcile_report.py``
    script only has to fetch ``(date, amount)`` pairs and the account's current
    cleared balance from YNAB.

    Parameters
    ----------
    statement : StatementInfo
        The parsed statement for this account.
    cleared_transactions : list of (datetime.date, float)
        Every *cleared* (or reconciled) transaction's date and dollar amount.
    current_cleared_balance : float
        The account's cleared balance right now.

    Notes
    -----
    ``activity_drift`` (the monthly-net-diff over the statement period) is the
    trustworthy signal — it only sums in-period transactions, so it flags real
    per-period divergence. ``balance_drift`` derives ``cleared_as_of_close`` by
    backing post-close cleared entries out of the current balance; that back-out is
    still balance-anchored, so pre-close phantom entries can bias it. Treat
    ``activity_drift`` as the red flag and let the YNAB app compute the authoritative
    adjustment when the user enters the statement balance.
    """
    ynab_net_over_period = round(
        sum(
            amt
            for d, amt in cleared_transactions
            if statement.period_start <= d <= statement.period_end
        ),
        2,
    )
    cleared_after_close = round(
        sum(amt for d, amt in cleared_transactions if d > statement.period_end), 2
    )
    ynab_cleared_as_of_close = round(current_cleared_balance - cleared_after_close, 2)
    return compute_drift(statement, ynab_net_over_period, ynab_cleared_as_of_close)


def _extract_date(filename: str) -> date | None:
    if m := re.search(r"(20\d{2})(\d{2})(\d{2})", filename):  # 20YYMMDD run
        y, mo, d = (int(g) for g in m.groups())
    elif m := re.search(r"(20\d{2})-(\d{2})-(\d{2})", filename):  # 20YY-MM-DD
        y, mo, d = (int(g) for g in m.groups())
    elif m := re.search(
        r"([A-Z][a-z]{2}) (\d{1,2}), (20\d{2})", filename
    ):  # Mon DD, YYYY
        y, mo, d = int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2))
    elif m := re.search(
        r"([a-z]{3})_(\d{1,2})_(20\d{2})", filename.lower()
    ):  # mon_dd_yyyy
        y, mo, d = int(m.group(3)), _MONTHS[m.group(1)], int(m.group(2))
    else:
        return None
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def _is_ally_file(filename: str) -> bool:
    name = filename.lower()
    return "ally" in name or bool(re.match(r"[a-z]{3}_\d{1,2}_20\d{2}_statement", name))


def resolve_statement_file(
    bank: str,
    account_tail: str,
    filenames: list[str],
    override: str | None = None,
) -> str | None:
    """Pick the newest statement file for an account from a candidate list.

    Chase files carry the account tail in the name; Ally emits one *combined*
    statement per period with no tail, matched by bank instead (its accounts are
    split apart later by :func:`parse_statement_text`). Tolerant of Chase's shifting
    filename conventions.

    Returns
    -------
    str | None
        The newest matching filename, ``override`` if given, or ``None`` when nothing
        matches (→ the skill skips that account with reason "awaiting statement").
    """
    if override is not None:
        return override

    # Match the tail only when it is NOT embedded in a longer digit run -- otherwise a
    # tail like "0131" would match the date in "20250131-statements-8659-.pdf" and pick
    # the wrong account's statement.
    tail_re = re.compile(rf"(?<!\d){re.escape(account_tail)}(?!\d)")

    def matches(fn: str) -> bool:
        if bank == "ally":
            return _is_ally_file(fn)
        return bool(tail_re.search(fn)) and not _is_ally_file(fn)

    dated = [
        (d, fn)
        for fn in filenames
        if matches(fn) and (d := _extract_date(fn)) is not None
    ]
    if not dated:
        return None
    return max(dated, key=lambda pair: pair[0])[1]
