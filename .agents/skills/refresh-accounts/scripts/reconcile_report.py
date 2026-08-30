#!/usr/bin/env python3
"""Deterministic reconcile-drift report for ONE account, for the refresh-accounts skill.

Given a bank statement PDF (the single source of truth) and a YNAB account, this
extracts the statement's period + begin/end balances, then compares them to the
account's cleared activity via the **monthly-net-diff** method (``ynab_mcp.reconcile``).
It is **read-only** against YNAB -- it never writes, approves, or reconciles; it just
tells the agent + user what to expect so the user can reconcile in the YNAB app against
the statement.

Run from the repo root with ``uv run python`` so it picks up the project's deps.

Usage
-----
    uv run python .agents/skills/refresh-accounts/scripts/reconcile_report.py \
        --budget-id <id> --account-id <id> --statement <path.pdf> [--account-tail <NNNN>]

The ``--account-tail`` is required only for Ally *combined* statements (several accounts
in one PDF); Chase statements are single-account and infer their own tail.
"""

import argparse
import json
import sys

import ynab
from pypdf import PdfReader

from ynab_mcp.client import build_api_client, call_with_retry, resolve_budget_id
from ynab_mcp.config import Settings
from ynab_mcp.reconcile import (
    StatementParseError,
    account_drift_from_transactions,
    parse_statement_text,
)


def _extract_text(pdf_path: str) -> str:
    reader = PdfReader(pdf_path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _iso_or_none(value: object) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reconcile-drift report for one account."
    )
    parser.add_argument("--budget-id", default=None)
    parser.add_argument("--account-id", required=True)
    parser.add_argument(
        "--statement", required=True, help="Path to the account's statement PDF"
    )
    parser.add_argument(
        "--account-tail",
        default=None,
        help="Last 4 of the account (Ally combined statements)",
    )
    args = parser.parse_args()

    settings = Settings.from_env()
    budget_id = resolve_budget_id(args.budget_id, settings)
    client = build_api_client(settings)

    # 1. Parse the statement (the SSOT). A parse failure is a hard stop here.
    try:
        statement = parse_statement_text(
            _extract_text(args.statement), account_tail=args.account_tail
        )
    except (StatementParseError, FileNotFoundError, OSError) as exc:
        print(
            json.dumps(
                {"account_id": args.account_id, "status": "error", "detail": str(exc)}
            )
        )
        sys.exit(2)

    # 2. Fetch the account + its cleared transactions (read-only).
    accounts_api = ynab.AccountsApi(client)
    account = call_with_retry(
        lambda: accounts_api.get_account_by_id(
            plan_id=budget_id, account_id=args.account_id
        )
    ).data.account
    txn_api = ynab.TransactionsApi(client)
    transactions = call_with_retry(
        lambda: txn_api.get_transactions_by_account(
            plan_id=budget_id, account_id=args.account_id
        )
    ).data.transactions

    cleared = [
        (t.var_date, t.amount / 1000)
        for t in transactions
        if not t.deleted and t.cleared in ("cleared", "reconciled")
    ]
    drift = account_drift_from_transactions(
        statement, cleared, current_cleared_balance=account.cleared_balance / 1000
    )

    report = {
        "account_id": args.account_id,
        "account_name": account.name,
        "status": "ready",
        "bank": statement.bank,
        "account_tail": statement.account_tail,
        "statement_period": [
            statement.period_start.isoformat(),
            statement.period_end.isoformat(),
        ],
        "statement_ending_balance": statement.ending_balance,
        "statement_net": drift.statement_net,
        "ynab_activity_drift": drift.activity_drift,
        "ynab_balance_drift": drift.balance_drift,
        "expected_adjustment": drift.expected_adjustment,
        "last_reconciled_at": _iso_or_none(account.last_reconciled_at),
    }
    print(json.dumps(report, indent=2))
    print(
        f"\n{account.name}: statement {statement.period_start}"
        f"..{statement.period_end}, ending ${statement.ending_balance:,.2f}. "
        f"In-period activity drift ${drift.activity_drift:,.2f} (the trustworthy "
        f"signal). Reconcile in the YNAB app to the statement's closing balance; "
        f"expect a ~${drift.expected_adjustment:,.2f} adjustment.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
