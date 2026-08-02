"""Tests for check_no_approvals.py."""

import json
from types import SimpleNamespace

import pytest
from pytest_mock import MockerFixture

import check_no_approvals as cna


def _fake_txn(id_: str, approved: bool, deleted: bool = False) -> SimpleNamespace:
    return SimpleNamespace(id=id_, approved=approved, deleted=deleted)


def _patch_transactions(mocker: MockerFixture, transactions: list[SimpleNamespace]) -> None:
    mocker.patch("check_no_approvals.Settings.from_env", return_value=mocker.Mock())
    mocker.patch("check_no_approvals.resolve_budget_id", return_value="budget-1")
    mocker.patch("check_no_approvals.build_api_client", return_value=mocker.Mock())
    transactions_api = mocker.patch("check_no_approvals.ynab.TransactionsApi")
    transactions_api.return_value.get_transactions.return_value = SimpleNamespace(
        data=SimpleNamespace(transactions=transactions)
    )


def test_fetch_unapproved_ids_excludes_approved_and_deleted(
    mocker: MockerFixture,
) -> None:
    """Only non-approved, non-deleted transactions are returned."""
    _patch_transactions(
        mocker,
        [
            _fake_txn("t1", approved=False),
            _fake_txn("t2", approved=True),
            _fake_txn("t3", approved=False, deleted=True),
        ],
    )

    result = cna.fetch_unapproved_ids("budget-1")

    assert result == {"t1"}


def test_snapshot_writes_budget_id_and_ids(mocker: MockerFixture, tmp_path) -> None:
    """snapshot writes budget_id + sorted unapproved id list as JSON."""
    _patch_transactions(
        mocker, [_fake_txn("t2", approved=False), _fake_txn("t1", approved=False)]
    )
    snapshot_file = tmp_path / "snapshot.json"

    cna.cmd_snapshot(
        SimpleNamespace(budget_id="budget-1", snapshot_file=str(snapshot_file))
    )

    payload = json.loads(snapshot_file.read_text())
    assert payload == {"budget_id": "budget-1", "unapproved_ids": ["t1", "t2"]}


def test_verify_passes_when_nothing_was_approved(
    mocker: MockerFixture, tmp_path
) -> None:
    """verify exits 0 when every previously-unapproved id is still unapproved."""
    snapshot_file = tmp_path / "snapshot.json"
    snapshot_file.write_text(
        json.dumps({"budget_id": "budget-1", "unapproved_ids": ["t1", "t2"]})
    )
    _patch_transactions(
        mocker, [_fake_txn("t1", approved=False), _fake_txn("t2", approved=False)]
    )

    cna.cmd_verify(SimpleNamespace(snapshot_file=str(snapshot_file)))  # must not raise/exit


def test_verify_passes_when_new_unapproved_transactions_appear(
    mocker: MockerFixture, tmp_path
) -> None:
    """New unapproved transactions (e.g. a bank sync) don't trip the check."""
    snapshot_file = tmp_path / "snapshot.json"
    snapshot_file.write_text(
        json.dumps({"budget_id": "budget-1", "unapproved_ids": ["t1"]})
    )
    _patch_transactions(
        mocker, [_fake_txn("t1", approved=False), _fake_txn("t2", approved=False)]
    )

    cna.cmd_verify(SimpleNamespace(snapshot_file=str(snapshot_file)))  # must not raise/exit


def test_verify_fails_when_a_previously_unapproved_transaction_was_approved(
    mocker: MockerFixture, tmp_path
) -> None:
    """The core regression this script exists to catch."""
    snapshot_file = tmp_path / "snapshot.json"
    snapshot_file.write_text(
        json.dumps({"budget_id": "budget-1", "unapproved_ids": ["t1", "t2"]})
    )
    _patch_transactions(mocker, [_fake_txn("t1", approved=False)])  # t2 vanished

    with pytest.raises(SystemExit) as exc_info:
        cna.cmd_verify(SimpleNamespace(snapshot_file=str(snapshot_file)))

    assert exc_info.value.code == 1


def test_verify_fails_even_when_net_count_increased(
    mocker: MockerFixture, tmp_path
) -> None:
    """A bare count comparison would miss this: t2 got approved AND t3 is new,
    so the raw unapproved count goes UP even though a real approval happened."""
    snapshot_file = tmp_path / "snapshot.json"
    snapshot_file.write_text(
        json.dumps({"budget_id": "budget-1", "unapproved_ids": ["t1", "t2"]})
    )
    _patch_transactions(
        mocker,
        [_fake_txn("t1", approved=False), _fake_txn("t3", approved=False)],
    )

    with pytest.raises(SystemExit) as exc_info:
        cna.cmd_verify(SimpleNamespace(snapshot_file=str(snapshot_file)))

    assert exc_info.value.code == 1
