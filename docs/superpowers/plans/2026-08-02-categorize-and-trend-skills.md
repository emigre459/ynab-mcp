# Transaction Categorization & Trend-Analysis Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Formalize the live-prototyped workflow (best-effort transaction categorization + subscription-cadence anomaly detection) as two `.agents/skills/` skills, closing #26 and amending+closing #27.

**Architecture:** Two `SKILL.md` orchestration files calling existing YNAB MCP tools, no new MCP tool code. `categorize-unapproved-transactions` additionally bundles a small deterministic Python safety-check script (`scripts/check_no_approvals.py`) that independently verifies, outside any MCP tool call or agent behavior, that no transaction got approved during the skill's run.

**Tech Stack:** Markdown (`SKILL.md` frontmatter + prose), Python 3.13 for the bundled safety script (reusing `ynab_mcp.client`/`ynab_mcp.config`), `pytest`/`pytest-mock` for the script's tests, `gh` CLI for the GitHub issue amendment.

## Global Constraints

- Skills are authored with `anthropic-skills:skill-creator` (explicit user request).
- `categorize-unapproved-transactions` may only auto-write a category when it has tier-1 evidence: a matched Amazon order with a real order number + parseable item text (categorized by reading the text directly, never keyword/regex rules), or a `find-payee-transactions` history with ≥3 prior transactions and a `most_common_category` that isn't itself "Uncategorized." Everything else goes to needs-review, unwritten.
- `bulk-manage-transactions` operations must never include `approved`.
- `find-payee-transactions` calls run sequentially, never in parallel, to avoid unnecessary rate-limit pressure (retry/backoff now exists via #17, but avoiding the hit is still cheaper than retrying through it).
- Both skills key payee identity off `import_payee_name_original`, never `payee_name` alone (YNAB's payee-matching can silently merge unrelated real merchants).
- `check_no_approvals.py` talks to the YNAB API directly (via `ynab_mcp.client.build_api_client`/`ynab_mcp.config.Settings`), independent of any MCP tool call, and checks **set containment** of unapproved transaction IDs, not a bare count comparison.
- Neither skill's `allowed-tools` includes anything that can approve a transaction or manage scheduled transactions/payees.
- No new code under `src/` or `tests/` — this plan touches only `.agents/skills/` and (for #27) a `gh issue edit`.
- Reference spec: `docs/superpowers/specs/2026-08-02-transaction-categorization-and-trend-skills-design.md`.

---

## Task 1: `check_no_approvals.py` safety-check script (TDD)

**Files:**
- Create: `.agents/skills/categorize-unapproved-transactions/scripts/check_no_approvals.py`
- Create: `.agents/skills/categorize-unapproved-transactions/scripts/test_check_no_approvals.py`

**Interfaces:**
- Consumes: `ynab_mcp.client.build_api_client(settings) -> ynab.ApiClient`, `ynab_mcp.client.resolve_budget_id(budget_id, settings) -> str`, `ynab_mcp.client.call_with_retry(func) -> T`, `ynab_mcp.config.Settings.from_env() -> Settings`, `ynab.TransactionsApi(client).get_transactions(plan_id=...) -> response` where `response.data.transactions` is a list of objects with `.id`, `.approved`, `.deleted`.
- Produces: CLI `python check_no_approvals.py snapshot <snapshot_file> --budget-id <id>` (writes `{"budget_id": str, "unapproved_ids": list[str]}` as JSON to `snapshot_file`, prints a count) and `python check_no_approvals.py verify <snapshot_file>` (exit 0 + "OK: ..." on stdout if containment holds, exit 1 + "FAIL: ..." on stderr listing the exact offending IDs if not). Later tasks (the `categorize-unapproved-transactions` skill) invoke this CLI via `Bash`/`uv run python`.

- [ ] **Step 1: Write the failing tests**

```python
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


def test_snapshot_writes_budget_id_and_ids(
    mocker: MockerFixture, tmp_path
) -> None:
    """snapshot writes budget_id + sorted unapproved id list as JSON."""
    _patch_transactions(mocker, [_fake_txn("t2", approved=False), _fake_txn("t1", approved=False)])
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
    snapshot_file.write_text(json.dumps({"budget_id": "budget-1", "unapproved_ids": ["t1", "t2"]}))
    _patch_transactions(mocker, [_fake_txn("t1", approved=False), _fake_txn("t2", approved=False)])

    cna.cmd_verify(SimpleNamespace(snapshot_file=str(snapshot_file)))  # must not raise/exit


def test_verify_passes_when_new_unapproved_transactions_appear(
    mocker: MockerFixture, tmp_path
) -> None:
    """New unapproved transactions (e.g. a bank sync) don't trip the check."""
    snapshot_file = tmp_path / "snapshot.json"
    snapshot_file.write_text(json.dumps({"budget_id": "budget-1", "unapproved_ids": ["t1"]}))
    _patch_transactions(
        mocker, [_fake_txn("t1", approved=False), _fake_txn("t2", approved=False)]
    )

    cna.cmd_verify(SimpleNamespace(snapshot_file=str(snapshot_file)))  # must not raise/exit


def test_verify_fails_when_a_previously_unapproved_transaction_was_approved(
    mocker: MockerFixture, tmp_path
) -> None:
    """The core regression this script exists to catch."""
    snapshot_file = tmp_path / "snapshot.json"
    snapshot_file.write_text(json.dumps({"budget_id": "budget-1", "unapproved_ids": ["t1", "t2"]}))
    _patch_transactions(mocker, [_fake_txn("t1", approved=False)])  # t2 vanished from unapproved

    with pytest.raises(SystemExit) as exc_info:
        cna.cmd_verify(SimpleNamespace(snapshot_file=str(snapshot_file)))

    assert exc_info.value.code == 1


def test_verify_fails_even_when_net_count_increased(
    mocker: MockerFixture, tmp_path
) -> None:
    """A bare count comparison would miss this: t2 got approved AND t3 is new,
    so the raw unapproved count goes UP even though a real approval happened."""
    snapshot_file = tmp_path / "snapshot.json"
    snapshot_file.write_text(json.dumps({"budget_id": "budget-1", "unapproved_ids": ["t1", "t2"]}))
    _patch_transactions(
        mocker,
        [_fake_txn("t1", approved=False), _fake_txn("t3", approved=False)],  # t2 approved, t3 new
    )

    with pytest.raises(SystemExit) as exc_info:
        cna.cmd_verify(SimpleNamespace(snapshot_file=str(snapshot_file)))

    assert exc_info.value.code == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/davemcrench/Projects/ynab-mcp/.claude/worktrees/categorize-and-trend-skills
uv run pytest .agents/skills/categorize-unapproved-transactions/scripts/test_check_no_approvals.py -v
```

Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'check_no_approvals'` (the module doesn't exist yet).

- [ ] **Step 3: Write the implementation**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/davemcrench/Projects/ynab-mcp/.claude/worktrees/categorize-and-trend-skills
uv run pytest .agents/skills/categorize-unapproved-transactions/scripts/test_check_no_approvals.py -v
```

Expected: PASS — 6 passed.

- [ ] **Step 5: Smoke-test the CLI against nothing (argparse wiring only)**

```bash
uv run python .agents/skills/categorize-unapproved-transactions/scripts/check_no_approvals.py --help
uv run python .agents/skills/categorize-unapproved-transactions/scripts/check_no_approvals.py snapshot --help
uv run python .agents/skills/categorize-unapproved-transactions/scripts/check_no_approvals.py verify --help
```

Expected: each prints usage help with no traceback.

- [ ] **Step 6: Commit**

```bash
git add .agents/skills/categorize-unapproved-transactions/scripts/check_no_approvals.py \
        .agents/skills/categorize-unapproved-transactions/scripts/test_check_no_approvals.py
git commit -m "$(cat <<'EOF'
Add deterministic approval-safety check script for #26

Independent of any MCP tool call or skill prose: snapshots the
unapproved transaction id set before categorization, verifies set
containment after. Catches the case a bare count comparison would
miss (some approved while unrelated new ones arrive in the same
window).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Amend #27's acceptance criteria for subscription-cadence detection

**Files:** none (GitHub issue only)

**Interfaces:** none

- [ ] **Step 1: Read the current issue body**

```bash
gh issue view 27 --json body -q .body
```

- [ ] **Step 2: Amend the body to add the new acceptance criterion**

Append a bullet to the existing `- **Acceptance:**` list (keep all existing bullets unchanged) reading:

```
  - Detects likely duplicate/overlapping subscriptions by pulling full per-payee transaction history for recurring-looking charges, computing gaps between charge dates, and checking whether the sequence decomposes into multiple overlapping ~monthly cycles rather than one; cross-checks flagged amounts against real-world vendor pricing via web search before surfacing them as a Lingering Question
```

Use `gh issue edit 27 --body-file -` piping the amended full body (existing content + new bullet, verbatim) so nothing else in the issue is lost.

- [ ] **Step 3: Verify the amendment landed**

```bash
gh issue view 27 --json body -q .body | grep "recurring-looking charges"
```

Expected: the new bullet text is present.

- [ ] **Step 4: Commit**

No commit — this step only touches GitHub, not the repo. Proceed to Task 3.

---

## Task 3: `categorize-unapproved-transactions` skill

**Files:**
- Create: `.agents/skills/categorize-unapproved-transactions/SKILL.md`

**Interfaces:**
- Consumes: `check_no_approvals.py`'s CLI from Task 1 (`snapshot <file> --budget-id <id>` / `verify <file>`); MCP tools `list-transactions`, `list-categories`, `find-payee-transactions`, `find-amazon-transactions`, `bulk-manage-transactions`.
- Produces: the `/categorize-unapproved-transactions` skill, invocable by name or natural-language trigger.

- [ ] **Step 1: Invoke skill-creator**

```
Skill(skill: "anthropic-skills:skill-creator", args: "create a new skill named categorize-unapproved-transactions in .agents/skills/, per docs/superpowers/specs/2026-08-02-transaction-categorization-and-trend-skills-design.md")
```

Follow skill-creator's own process for scaffolding frontmatter and structure.

- [ ] **Step 2: Write the skill body**

Populate `SKILL.md` with the full workflow from the design doc's "Skill: `categorize-unapproved-transactions` (#26)" section verbatim as the basis: the 8-step flow (budget_id resolution + snapshot, pull unapproved transactions + categories, payee normalization via `import_payee_name_original`, `find-amazon-transactions`/sequential `find-payee-transactions` calls, tier classification, batched `bulk-manage-transactions` write with evidence memo, `verify` call, structured + human-readable summary), the tier-1/tier-2 evidence bar from the design's Decision 4, the Amazon item-categorization guidance (read the text, don't regex — cite the two false-positive examples from the design doc so the instruction has a concrete "why"), the payee data-quality check, the error-handling rule for partial `bulk-manage-transactions` failures, and the `allowed-tools` list from the design's "Shared conventions" section (`list-transactions`, `list-categories`, `find-payee-transactions`, `find-amazon-transactions`, `bulk-manage-transactions`, `AskUserQuestion`, `Bash`).

- [ ] **Step 3: Self-check against the design doc**

Re-read `docs/superpowers/specs/2026-08-02-transaction-categorization-and-trend-skills-design.md`'s `categorize-unapproved-transactions` section line by line against the written `SKILL.md`; confirm every flow step, the tier bar, and the safety-check integration are represented. Fix any gaps inline.

- [ ] **Step 4: Commit**

```bash
git add .agents/skills/categorize-unapproved-transactions/SKILL.md
git commit -m "$(cat <<'EOF'
Add categorize-unapproved-transactions skill

Closes #26.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `analyze-budget-trends` skill

**Files:**
- Create: `.agents/skills/analyze-budget-trends/SKILL.md`

**Interfaces:**
- Consumes: MCP tools `list-transactions`, `flag-category-spend`, `analyze-category-trends`, `find-payee-transactions`; `WebSearch`. Assumes `categorize-unapproved-transactions` already ran for the target month (documented dependency, not enforced in code).
- Produces: the `/analyze-budget-trends` skill, invocable by name or natural-language trigger.

- [ ] **Step 1: Invoke skill-creator**

```
Skill(skill: "anthropic-skills:skill-creator", args: "create a new skill named analyze-budget-trends in .agents/skills/, per docs/superpowers/specs/2026-08-02-transaction-categorization-and-trend-skills-design.md")
```

- [ ] **Step 2: Write the skill body**

Populate `SKILL.md` with the full workflow from the design doc's "Skill: `analyze-budget-trends` (#27, amended)" section: budget_id + target month resolution (must accept an arbitrary month, not just "current"), `flag-category-spend`/`analyze-category-trends` calls bucketed into successes/failures, suggested budgeted-amount changes (proposal only, never written), the subscription-cadence detection technique (pull full per-payee history, compute date-gaps, decompose into overlapping cycles, cross-check via `WebSearch` against real vendor pricing — reference the Lumosity/FuboTV session as the worked example), the "Lingering Questions" assembly rule (every candidate needs ≥1 plausible explanation, never a bare "this looks weird"), the documented dependency on `categorize-unapproved-transactions` having already run, and the `allowed-tools` list (`list-transactions`, `flag-category-spend`, `analyze-category-trends`, `find-payee-transactions`, `WebSearch`, `AskUserQuestion`, `Bash`).

- [ ] **Step 3: Self-check against the amended #27**

```bash
gh issue view 27 --json body -q .body
```

Confirm every acceptance bullet (including the Task 2 amendment) maps to something the written `SKILL.md` actually does. Fix any gaps inline.

- [ ] **Step 4: Commit**

```bash
git add .agents/skills/analyze-budget-trends/SKILL.md
git commit -m "$(cat <<'EOF'
Add analyze-budget-trends skill

Closes #27.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Verify and open the PR

**Files:** none (verification + GitHub only)

**Interfaces:** none

- [ ] **Step 1: Confirm the wider repo quality gates are unaffected**

```bash
cd /Users/davemcrench/Projects/ynab-mcp/.claude/worktrees/categorize-and-trend-skills
make lint
make tests
```

Expected: both pass, unchanged from before this branch (the new script lives outside `src`/`tests`, so this is a regression check, not new coverage).

- [ ] **Step 2: Run the new script's tests one more time in isolation**

```bash
uv run pytest .agents/skills/categorize-unapproved-transactions/scripts/test_check_no_approvals.py -v
```

Expected: PASS — 6 passed.

- [ ] **Step 3: Push and open the PR**

```bash
git push -u origin worktree-categorize-and-trend-skills
gh pr create --title "Add categorize-unapproved-transactions and analyze-budget-trends skills" --body "$(cat <<'EOF'
## Summary
- Formalizes the live-prototyped monthly-review workflow (best-effort transaction categorization + subscription-cadence anomaly detection) as two `.agents/skills/` skills.
- `categorize-unapproved-transactions` writes `category_id` only for tier-1 (hard-evidence) matches, leaving `approved` untouched, and verifies via an independent script (not skill prose) that nothing got approved.
- `analyze-budget-trends` amends #27 to add duplicate-subscription detection to its Lingering Questions criterion.

Closes #26.
Closes #27.

## Test plan
- [x] `check_no_approvals.py` unit tests (6 cases, including the count-vs-containment regression case)
- [x] `make lint` / `make tests` unaffected
- [ ] Live validation against the real budget (manual, post-merge)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Report the PR URL to the user**

Paste the URL `gh pr create` returns back to the user; do not merge.
