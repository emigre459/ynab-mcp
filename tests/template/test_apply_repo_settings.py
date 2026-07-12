from pathlib import Path

from scripts.apply_repo_settings import (
    find_main_ruleset,
    ruleset_matches,
    merge_settings_match,
    plan_actions,
    load_desired,
)

REPO_SETTINGS = Path(__file__).resolve().parents[2] / ".github" / "repo-settings"


def test_load_desired_reads_both_files() -> None:
    desired = load_desired(REPO_SETTINGS)
    assert desired.ruleset["name"] == "main"
    assert desired.merge["allow_squash_merge"] is True


def test_find_main_ruleset_returns_match() -> None:
    existing = [{"id": 1, "name": "other"}, {"id": 2, "name": "main"}]
    result = find_main_ruleset(existing)
    assert result is not None
    assert result["id"] == 2


def test_find_main_ruleset_none_when_absent() -> None:
    assert find_main_ruleset([{"id": 1, "name": "develop"}]) is None


def test_ruleset_matches_true_when_rules_equal() -> None:
    desired = {"name": "main", "enforcement": "active", "rules": [{"type": "deletion"}]}
    current = {
        "name": "main",
        "enforcement": "active",
        "rules": [{"type": "deletion"}],
        "id": 99,
        "created_at": "x",
    }
    assert ruleset_matches(desired, current) is True


def test_ruleset_matches_false_when_rules_differ() -> None:
    desired = {"name": "main", "enforcement": "active", "rules": [{"type": "deletion"}]}
    current = {"name": "main", "enforcement": "active", "rules": []}
    assert ruleset_matches(desired, current) is False


def test_ruleset_matches_true_when_current_has_api_defaults() -> None:
    # GitHub returns rules/conditions with extra default-populated fields our
    # sanitized ruleset.json omits — subset matching must still consider it aligned.
    desired = {
        "name": "main",
        "enforcement": "active",
        "rules": [
            {"type": "deletion"},
            {
                "type": "pull_request",
                "parameters": {"allowed_merge_methods": ["squash"]},
            },
        ],
    }
    current = {
        "name": "main",
        "enforcement": "active",
        "id": 7,
        "created_at": "2026-01-01",
        "rules": [
            {"type": "deletion"},
            {
                "type": "pull_request",
                "parameters": {
                    "allowed_merge_methods": ["squash"],
                    "required_approving_review_count": 0,
                    "dismiss_stale_reviews_on_push": True,
                },
            },
            {"type": "non_fast_forward"},
        ],
    }
    assert ruleset_matches(desired, current) is True


def test_merge_settings_match_ignores_extra_current_keys() -> None:
    desired = {"allow_squash_merge": True, "allow_merge_commit": False}
    current = {"allow_squash_merge": True, "allow_merge_commit": False, "extra": 1}
    assert merge_settings_match(desired, current) is True


def test_plan_actions_post_when_no_ruleset() -> None:
    desired_rs = {"name": "main", "enforcement": "active", "rules": []}
    desired_merge = {"allow_squash_merge": True}
    actions = plan_actions(
        current_rulesets=[],
        current_merge={"allow_squash_merge": False},
        desired_ruleset=desired_rs,
        desired_merge=desired_merge,
    )
    assert ("ruleset", "POST", None) in actions
    assert any(a[0] == "merge" and a[1] == "PATCH" for a in actions)


def test_plan_actions_put_when_main_exists_and_differs() -> None:
    desired_rs = {
        "name": "main",
        "enforcement": "active",
        "rules": [{"type": "deletion"}],
    }
    actions = plan_actions(
        current_rulesets=[
            {"id": 7, "name": "main", "enforcement": "active", "rules": []}
        ],
        current_merge={"allow_squash_merge": True},
        desired_ruleset=desired_rs,
        desired_merge={"allow_squash_merge": True},
    )
    assert ("ruleset", "PUT", 7) in actions
    assert all(a[0] != "merge" for a in actions)  # merge already aligned → no-op


def test_plan_actions_all_noop_when_aligned() -> None:
    desired_rs = {
        "name": "main",
        "enforcement": "active",
        "rules": [{"type": "deletion"}],
    }
    actions = plan_actions(
        current_rulesets=[
            {
                "id": 7,
                "name": "main",
                "enforcement": "active",
                "rules": [{"type": "deletion"}],
            }
        ],
        current_merge={"allow_squash_merge": True},
        desired_ruleset=desired_rs,
        desired_merge={"allow_squash_merge": True},
    )
    assert actions == []
