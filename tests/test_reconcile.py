"""Tests for ``ynab_mcp.reconcile`` — pure statement-parsing + drift logic.

All fixtures are synthetic (crafted, non-real) text/numbers/filenames — no real
financial statements are committed. The pure functions take text/number inputs so
they are fully testable without PDFs or network.
"""

from datetime import date

import pytest

from ynab_mcp.reconcile import (
    DriftResult,
    StatementInfo,
    StatementParseError,
    compute_drift,
    parse_statement_text,
    resolve_statement_file,
)

# --- synthetic statement text (mirrors the real layouts' key lines only) ---

CHASE_TEXT = """\
JPMorgan Chase Bank, N.A.
January 30, 2026 through February 27, 2026
Account Number: 000000000330033
CHECKING SUMMARY
Beginning Balance $3,296.04
Ending Balance $868.84
"""

ALLY_TEXT = """\
Ally Bank Member FDIC
Money Market Savings
Account Number: xxxxxx5170 Open Date: 11/02/2024
Beginning Balance, as of 07/24/2026 $15,348.12
Ending Balance, as of 08/23/2026 $11,384.76
Spending Account
Account Number: xxxxxx5181 Open Date: 11/02/2024
Beginning Balance, as of 07/24/2026 $528.07
Ending Balance, as of 08/23/2026 $528.11
"""


class TestParseStatementText:
    def test_chase_single_account(self):
        info = parse_statement_text(CHASE_TEXT)
        assert info.bank == "chase"
        assert info.account_tail == "0033"
        assert info.period_start == date(2026, 1, 30)
        assert info.period_end == date(2026, 2, 27)
        assert info.beginning_balance == 3296.04
        assert info.ending_balance == 868.84
        assert info.statement_net == -2427.20

    def test_ally_selects_account_by_tail(self):
        info = parse_statement_text(ALLY_TEXT, account_tail="5181")
        assert info.bank == "ally"
        assert info.account_tail == "5181"
        assert info.period_start == date(2026, 7, 24)
        assert info.period_end == date(2026, 8, 23)
        assert info.beginning_balance == 528.07
        assert info.ending_balance == 528.11

    def test_ally_other_account_by_tail(self):
        info = parse_statement_text(ALLY_TEXT, account_tail="5170")
        assert info.beginning_balance == 15348.12
        assert info.ending_balance == 11384.76

    def test_ally_requires_tail_when_multiple(self):
        with pytest.raises(StatementParseError):
            parse_statement_text(ALLY_TEXT)  # ambiguous: no tail given

    def test_unrecognized_format_raises(self):
        with pytest.raises(StatementParseError):
            parse_statement_text("just some random text with no bank markers")


class TestComputeDrift:
    def _stmt(self, begin, end):
        return StatementInfo(
            bank="chase",
            account_tail="0033",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            beginning_balance=begin,
            ending_balance=end,
        )

    def test_exact_match_zero_drift(self):
        stmt = self._stmt(1000.00, 1500.00)
        # YNAB recorded the same +500 activity and lands exactly on the statement close
        res = compute_drift(stmt, ynab_net_over_period=500.00, ynab_cleared_as_of_close=1500.00)
        assert isinstance(res, DriftResult)
        assert res.statement_net == 500.00
        assert res.activity_drift == 0.00
        assert res.balance_drift == 0.00
        assert res.expected_adjustment == 0.00

    def test_ynab_high_residual(self):
        stmt = self._stmt(1000.00, 1500.00)
        res = compute_drift(stmt, ynab_net_over_period=500.00, ynab_cleared_as_of_close=1600.00)
        assert res.balance_drift == 100.00  # YNAB $100 high vs statement
        assert res.expected_adjustment == -100.00  # adjust YNAB down $100 to match

    def test_activity_drift_immune_to_phantom_noise(self):
        # Statement net is -1236.11; YNAB's cleared net over the same period is -990.44
        # (it happens to include phantom entries, but the monthly-net-diff still reports
        # the true activity gap without any balance-anchor contamination).
        stmt = self._stmt(3866.49, 2630.38)
        res = compute_drift(stmt, ynab_net_over_period=-990.44, ynab_cleared_as_of_close=2630.38)
        assert res.statement_net == -1236.11
        assert res.activity_drift == 245.67
        assert res.balance_drift == 0.00


class TestResolveStatementFile:
    def test_override_short_circuits(self):
        assert resolve_statement_file("chase", "0033", ["a.pdf"], override="/x/y.pdf") == "/x/y.pdf"

    def test_chase_newest_by_tail_across_conventions(self):
        files = [
            "20250131-statements-0033-.pdf",
            "0033 - Checking - Jun 30, 2026.pdf",
            "2026-02-27_Chase_Checking.pdf",  # renamed convention, no tail — ignored for tail match
            "8659 - Savings - Aug 21, 2026.pdf",  # different account
        ]
        # newest 0033 by date is Jun 30 2026
        assert resolve_statement_file("chase", "0033", files) == "0033 - Checking - Jun 30, 2026.pdf"

    def test_ally_matches_by_bank_not_tail(self):
        files = [
            "aug_24_2026_statement.pdf",
            "20251224_Ally.pdf",
            "0033 - Checking - Jun 30, 2026.pdf",  # chase, ignored
        ]
        assert resolve_statement_file("ally", "5181", files) == "aug_24_2026_statement.pdf"

    def test_no_match_returns_none(self):
        assert resolve_statement_file("chase", "0033", ["8659 - Savings - Aug 21, 2026.pdf"]) is None
