"""Regression test for the ``reconcile_report.py`` skill script.

The script lives under ``.agents/skills/refresh-accounts/scripts/`` (not
``src/ynab_mcp/``), so it's loaded by file path rather than imported normally.
Everything I/O-facing (settings, the API client, the YNAB SDK's API classes,
PDF text extraction) is monkeypatched; only the script's own call-construction
logic is under test.
"""

import importlib.util
import sys
from collections.abc import Generator
from datetime import date
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import ynab

SCRIPT_PATH = (
    Path(__file__).parent.parent
    / ".agents"
    / "skills"
    / "refresh-accounts"
    / "scripts"
    / "reconcile_report.py"
)

# Mirrors the real Chase pypdf layout closely enough for parse_statement_text.
CHASE_TEXT = """\
 000000872910033
JPMorgan Chase Bank, N.A.
August 01, 2026 through August 31, 2026
Account Number:
009180241474
CHECKING SUMMARY
Beginning Balance $1,826.44
Ending Balance $1,334.48
Page 2 of 2
 000000872910033
JPMorgan Chase Bank, N.A. Member FDIC
"""


@pytest.fixture
def script_module() -> Generator[ModuleType]:
    spec = importlib.util.spec_from_file_location(
        "reconcile_report_script", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    del sys.modules[spec.name]


def test_fetches_transactions_since_statement_period_start(
    script_module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test for the missing ``since_date`` bug.

    The bundled ynab SDK defaults ``since_date`` to one year ago when it's
    omitted -- silently truncating history for any statement period older than
    that. The script must always pass an explicit ``since_date`` so a statement
    period from further back still gets its full cleared-transaction history.
    """
    captured: dict[str, object] = {}

    class FakeAccountsApi:
        def __init__(self, client: object) -> None:
            pass

        def get_account_by_id(self, plan_id: str, account_id: str) -> SimpleNamespace:
            account = SimpleNamespace(
                name="Chase Checking",
                cleared_balance=1_334_480,
                last_reconciled_at=None,
            )
            return SimpleNamespace(data=SimpleNamespace(account=account))

    class FakeTransactionsApi:
        def __init__(self, client: object) -> None:
            pass

        def get_transactions_by_account(
            self, plan_id: str, account_id: str, since_date: date | None = None
        ) -> SimpleNamespace:
            captured["since_date"] = since_date
            return SimpleNamespace(data=SimpleNamespace(transactions=[]))

    monkeypatch.setattr(ynab, "AccountsApi", FakeAccountsApi)
    monkeypatch.setattr(ynab, "TransactionsApi", FakeTransactionsApi)
    monkeypatch.setattr(script_module, "_extract_text", lambda path: CHASE_TEXT)
    monkeypatch.setattr(
        script_module.Settings, "from_env", staticmethod(lambda: object())
    )
    monkeypatch.setattr(script_module, "resolve_budget_id", lambda *a, **k: "budget-1")
    monkeypatch.setattr(script_module, "build_api_client", lambda settings: object())
    monkeypatch.setattr(script_module, "call_with_retry", lambda fn, **kwargs: fn())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "reconcile_report.py",
            "--account-id",
            "acct-1",
            "--statement",
            "unused.pdf",
        ],
    )

    script_module.main()

    assert captured["since_date"] == date(2026, 8, 1)
