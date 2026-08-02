#!/usr/bin/env python3
"""Deterministic, agent-independent safety check for categorize-unapproved-transactions.

Verifies -- via a real subprocess, not skill prose -- that no transaction which
was unapproved before the categorization pass has become approved after it.
Checks set containment of unapproved transaction IDs, not a bare count
comparison: a count alone can mask the exact bug this guards against (some
transactions wrongly approved while unrelated new ones arrive in the same
window, netting a count that still looks fine).

Usage:
    uv run python check_no_approvals.py snapshot <snapshot_file> --budget-id <id>
    uv run python check_no_approvals.py verify <snapshot_file>
"""

import argparse
import json
import sys
from pathlib import Path

import ynab

from ynab_mcp.client import build_api_client, call_with_retry, resolve_budget_id
from ynab_mcp.config import Settings


def fetch_unapproved_ids(budget_id: str) -> set[str]:
    """Fetch the set of currently unapproved, non-deleted transaction ids.

    Parameters
    ----------
    budget_id : str
        The YNAB budget id to check.

    Returns
    -------
    set[str]
        Transaction ids where ``approved`` is False and ``deleted`` is False.
    """
    settings = Settings.from_env()
    resolved_budget_id = resolve_budget_id(budget_id, settings)
    client = build_api_client(settings)
    api = ynab.TransactionsApi(client)
    response = call_with_retry(
        lambda: api.get_transactions(plan_id=resolved_budget_id)
    )
    return {
        t.id for t in response.data.transactions if not t.approved and not t.deleted
    }


def cmd_snapshot(args: argparse.Namespace) -> None:
    """Write the current unapproved transaction id set to ``args.snapshot_file``."""
    ids = fetch_unapproved_ids(args.budget_id)
    payload = {"budget_id": args.budget_id, "unapproved_ids": sorted(ids)}
    Path(args.snapshot_file).write_text(json.dumps(payload, indent=2))
    print(f"Snapshot: {len(ids)} unapproved transactions -> {args.snapshot_file}")


def cmd_verify(args: argparse.Namespace) -> None:
    """Verify every id in the snapshot is still unapproved; exit 1 if not."""
    payload = json.loads(Path(args.snapshot_file).read_text())
    before_ids = set(payload["unapproved_ids"])
    after_ids = fetch_unapproved_ids(payload["budget_id"])

    missing = before_ids - after_ids
    if missing:
        print(
            f"FAIL: {len(missing)} transaction(s) unapproved at snapshot time are "
            f"no longer unapproved -- they may have been approved: {sorted(missing)}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(
        f"OK: all {len(before_ids)} previously-unapproved transactions are still "
        f"unapproved (now {len(after_ids)} unapproved total, "
        f"{len(after_ids) - len(before_ids)} net new)."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot_parser = subparsers.add_parser(
        "snapshot", help="Record the current unapproved transaction id set."
    )
    snapshot_parser.add_argument("snapshot_file")
    snapshot_parser.add_argument("--budget-id", dest="budget_id", required=True)
    snapshot_parser.set_defaults(func=cmd_snapshot)

    verify_parser = subparsers.add_parser(
        "verify", help="Verify no previously-unapproved transaction was approved."
    )
    verify_parser.add_argument("snapshot_file")
    verify_parser.set_defaults(func=cmd_verify)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
