#!/usr/bin/env python3
"""Reconcile this repo's `main` ruleset + PR-merge prefs with .github/repo-settings/.

Reads the canonical settings, diffs them against the live repo (via `gh`), prints
the diff, and — unless ``--yes`` — asks for confirmation before applying. Idempotent.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_SETTINGS_DIR = Path(__file__).resolve().parent.parent / ".github" / "repo-settings"

# Ruleset fields we assert; everything else (id, timestamps, _links) is ignored.
_RULESET_KEYS = (
    "name",
    "target",
    "enforcement",
    "conditions",
    "rules",
    "bypass_actors",
)


@dataclass
class Desired:
    """The canonical settings loaded from disk."""

    ruleset: dict
    merge: dict


def load_desired(settings_dir: Path) -> Desired:
    """Load the desired ruleset + merge settings from ``settings_dir``."""
    ruleset = json.loads((settings_dir / "ruleset.json").read_text(encoding="utf-8"))
    merge = json.loads(
        (settings_dir / "merge-settings.json").read_text(encoding="utf-8")
    )
    return Desired(ruleset=ruleset, merge=merge)


def find_main_ruleset(existing: list[dict]) -> dict | None:
    """Return the ruleset named ``main`` from ``existing``, or None."""
    for rs in existing:
        if rs.get("name") == "main":
            return rs
    return None


def _is_subset(desired: object, current: object) -> bool:
    """Return True when ``desired`` is contained in ``current`` (recursively).

    GitHub's rulesets API returns rules/conditions with default-populated fields
    that our sanitized ruleset.json omits, so a strict ``==`` would never match an
    already-applied ruleset and we'd re-PUT it every run. Subset semantics: dicts
    match when every desired key is present and contained; lists match when each
    desired element is contained in some current element; scalars match on ``==``.
    """
    if isinstance(desired, dict):
        if not isinstance(current, dict):
            return False
        return all(
            k in current and _is_subset(v, current[k]) for k, v in desired.items()
        )
    if isinstance(desired, list):
        if not isinstance(current, list):
            return False
        return all(any(_is_subset(d, c) for c in current) for d in desired)
    return desired == current


def ruleset_matches(desired: dict, current: dict) -> bool:
    """Return True when ``current`` already satisfies ``desired`` on the asserted keys.

    Uses subset (not strict-equality) comparison so GitHub's API-default fields on
    the live ruleset don't cause a spurious "needs update" every run.
    """
    return all(
        _is_subset(desired[k], current.get(k)) for k in _RULESET_KEYS if k in desired
    )


def merge_settings_match(desired: dict, current: dict) -> bool:
    """Return True when every desired merge key already has the desired value."""
    return all(current.get(k) == v for k, v in desired.items())


def plan_actions(
    current_rulesets: list[dict],
    current_merge: dict,
    desired_ruleset: dict,
    desired_merge: dict,
) -> list[tuple]:
    """Compute the minimal set of apply actions.

    Returns a list of tuples: ``("ruleset", "POST"|"PUT", id_or_None)`` and/or
    ``("merge", "PATCH", None)``. Empty list means everything is already aligned.
    """
    actions: list[tuple] = []
    main = find_main_ruleset(current_rulesets)
    if main is None:
        actions.append(("ruleset", "POST", None))
    elif not ruleset_matches(desired_ruleset, main):
        actions.append(("ruleset", "PUT", main["id"]))
    if not merge_settings_match(desired_merge, current_merge):
        actions.append(("merge", "PATCH", None))
    return actions


def _gh_json(args: list[str], runner: Callable[..., Any] = subprocess.run) -> Any:
    """Run a `gh` command and parse its stdout as JSON."""
    proc = runner(["gh", *args], capture_output=True, text=True, check=True)
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def _current_repo(runner: Callable[..., Any] = subprocess.run) -> str:
    proc = runner(
        ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
        capture_output=True,
        text=True,
        check=True,
    )
    return str(proc.stdout).strip()


def main(
    argv: list[str] | None = None,
    runner: Callable[..., Any] = subprocess.run,
) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="apply without confirmation")
    parser.add_argument("--settings-dir", default=str(REPO_SETTINGS_DIR))
    args = parser.parse_args(argv)

    desired = load_desired(Path(args.settings_dir))
    repo = _current_repo(runner)
    current_rulesets = _gh_json(["api", f"repos/{repo}/rulesets"], runner) or []
    current_merge = _gh_json(["api", f"repos/{repo}"], runner) or {}

    actions = plan_actions(
        current_rulesets, current_merge, desired.ruleset, desired.merge
    )
    if not actions:
        print(f"{repo}: settings already aligned — no changes.")
        return 0

    print(f"{repo}: planned changes:")
    for kind, method, ident in actions:
        print(f"  - {kind}: {method}" + (f" (id={ident})" if ident else ""))

    if not args.yes:
        reply = input("Apply these changes? [y/N] ").strip().lower()
        if reply != "y":
            print("Aborted.")
            return 1

    for kind, method, ident in actions:
        if kind == "ruleset" and method == "POST":
            runner(
                [
                    "gh",
                    "api",
                    "--method",
                    "POST",
                    f"repos/{repo}/rulesets",
                    "--input",
                    "-",
                ],
                input=json.dumps(desired.ruleset),
                text=True,
                check=True,
            )
        elif kind == "ruleset" and method == "PUT":
            runner(
                [
                    "gh",
                    "api",
                    "--method",
                    "PUT",
                    f"repos/{repo}/rulesets/{ident}",
                    "--input",
                    "-",
                ],
                input=json.dumps(desired.ruleset),
                text=True,
                check=True,
            )
        elif kind == "merge":
            # Send a typed JSON body (like the ruleset paths) rather than
            # `-f key=value` form fields: `gh api -f` sends every value as a
            # string, but the repo PATCH endpoint expects JSON booleans for
            # allow_squash_merge / delete_branch_on_merge / etc.
            runner(
                ["gh", "api", "--method", "PATCH", f"repos/{repo}", "--input", "-"],
                input=json.dumps(desired.merge),
                text=True,
                check=True,
            )
    print("Applied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
