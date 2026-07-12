#!/usr/bin/env python3
"""Initialize this dual-stack template into a single-stack project.

`make init STACK=python|react ...` promotes the chosen stack's files to the repo
root, prunes the other stack, rewrites the marker-wrapped generated files, applies
the repo settings, and deletes the template-only machinery.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

STACKS = ("python", "react")

# Files rewritten at init: (relative path, marker kind). "html" -> filter_html_markers,
# "yaml" -> filter_yaml_markers, "fill" -> placeholders only.
_HTML_FILES = ("AGENTS.md", "README.md")
_YAML_FILES = (".github/workflows/ci.yml", ".github/dependabot.yml")
_FILL_ONLY = (
    "AGENTS.md",
    "pyproject.toml",
    "package.json",
    "index.html",
    "src/App.tsx",
    "README.md",
)

# Manifests + lockfiles where the PEP 508 / npm-safe placeholder name must be
# replaced with the user's chosen project name. (See plan note in Task 16:
# {{PROJECT_NAME}} is invalid in these files, so we use a literal placeholder
# package name.) Lockfiles are included so they stay consistent with the manifest
# and the first `make deps` doesn't produce a spurious dirty diff.
_MANIFEST_FILES = ("pyproject.toml", "package.json", "uv.lock", "bun.lock")
_MANIFEST_PLACEHOLDER = "template-placeholder-project-name"

# Parallel CI jobs shipped per stack. Pre-init the job ids carry a stack prefix
# (both stacks coexist, duplicate ids are invalid YAML); init strips the kept
# stack's prefix and requires the resulting contexts as status checks.
_CI_JOBS = ("lint", "tests", "security")
# The GitHub Actions app — pinning integration_id means only Actions-reported
# check runs satisfy the required contexts.
_GITHUB_ACTIONS_INTEGRATION_ID = 15368


def _toml_escape(value: str) -> str:
    """Escape a string for a TOML basic (double-quoted) string value."""
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def _json_escape(value: str) -> str:
    """Escape a string for a JSON double-quoted string value (without the quotes)."""
    return json.dumps(value)[1:-1]


# Manifest/lockfile formats — the project name and description get spliced into
# quoted TOML/JSON string fields here, so values with ", \, or newlines must be
# escaped for the target format or they produce an invalid manifest.
_MANIFEST_FORMAT: dict[str, Callable[[str], str]] = {
    "pyproject.toml": _toml_escape,
    "uv.lock": _toml_escape,
    "package.json": _json_escape,
    "bun.lock": _json_escape,
}


def _other(stack: str) -> str:
    return "react" if stack == "python" else "python"


def filter_html_markers(text: str, keep: str) -> str:
    """Drop the non-kept stack's HTML-marker blocks; unwrap the kept stack's markers."""
    other = _other(keep)
    text = re.sub(
        rf"<!-- STACK:{other} -->.*?<!-- /STACK:{other} -->\n?", "", text, flags=re.S
    )
    text = re.sub(rf"<!-- /?STACK:{keep} -->\n?", "", text)
    return text


def filter_yaml_markers(text: str, keep: str) -> str:
    """Drop every YAML-marker block except the kept stack's; unwrap the kept markers.

    The ``template`` block is always dropped (machinery is removed post-init).
    """
    for name in ("python", "react", "template"):
        if name == keep:
            continue
        text = re.sub(
            rf"^[ \t]*# >>> STACK:{name}\b.*?^[ \t]*# <<< STACK:{name}\b.*?\n",
            "",
            text,
            flags=re.S | re.M,
        )
    text = re.sub(rf"^[ \t]*# (?:>>>|<<<) STACK:{keep}\b.*?\n", "", text, flags=re.M)
    return text


def strip_stack_job_prefix(text: str, stack: str) -> str:
    """Rename the kept stack's CI job ids from ``<stack>-<job>`` to ``<job>``.

    Only exact job-id lines are touched (two-space indent, known job names), so
    step names, paths, and other ``<stack>-`` strings are left alone.
    """
    return re.sub(
        rf"^  {re.escape(stack)}-({'|'.join(_CI_JOBS)}):",
        r"  \1:",
        text,
        flags=re.M,
    )


def strip_interview(text: str) -> str:
    """Remove the README interview prompt block."""
    return re.sub(
        r"<!-- INTERVIEW:start -->.*?<!-- INTERVIEW:end -->\n?", "", text, flags=re.S
    )


def fill_placeholders(text: str, project_name: str, description: str) -> str:
    """Replace ``{{PROJECT_NAME}}`` and ``{{DESCRIPTION}}`` tokens."""
    return text.replace("{{PROJECT_NAME}}", project_name).replace(
        "{{DESCRIPTION}}", description
    )


def _promote(root: Path, stack: str) -> None:
    """Move stacks/<stack>/* up to the repo root, replacing colliding entries."""
    chosen = root / "stacks" / stack
    for item in chosen.iterdir():
        dest = root / item.name
        if dest.is_dir():
            shutil.rmtree(dest)
        elif dest.exists():
            dest.unlink()
        shutil.move(str(item), str(dest))


def _rewrite_dependabot_dir(root: Path, stack: str) -> None:
    """After promotion the kept stack lives at root -> point dependabot at '/'."""
    path = root / ".github" / "dependabot.yml"
    if path.exists():
        text = path.read_text(encoding="utf-8").replace(f"/stacks/{stack}", "/")
        path.write_text(text, encoding="utf-8")


def _rewrite_ci_workdir(root: Path, stack: str) -> None:
    """After promotion the kept stack lives at root -> drop the stacks/ workdir.

    The kept CI job declares ``working-directory: stacks/<stack>``; once the stack
    is promoted to the repo root that path no longer exists, so point it at the
    repo root (``.``) — otherwise the spawned repo's first CI run fails.
    """
    path = root / ".github" / "workflows" / "ci.yml"
    if path.exists():
        text = path.read_text(encoding="utf-8").replace(
            f"working-directory: stacks/{stack}", "working-directory: ."
        )
        path.write_text(text, encoding="utf-8")


def _rewrite_ci_job_ids(root: Path, stack: str) -> None:
    """Strip the kept stack's prefix from CI job ids (see strip_stack_job_prefix)."""
    path = root / ".github" / "workflows" / "ci.yml"
    if path.exists():
        path.write_text(
            strip_stack_job_prefix(path.read_text(encoding="utf-8"), stack),
            encoding="utf-8",
        )


def _set_required_status_checks(root: Path) -> None:
    """Point the ruleset's required_status_checks at the seeded repo's CI jobs.

    The shipped ruleset.json requires the TEMPLATE repo's own CI contexts
    (stack-prefixed jobs + the template-machinery job), so `make
    apply_repo_settings` run on the template repo itself gates on its real CI.
    Seeded repos get plain lint/tests/security jobs (see _rewrite_ci_job_ids),
    so init rewrites the rule's contexts to match before settings are applied.
    """
    path = root / ".github" / "repo-settings" / "ruleset.json"
    if not path.exists():
        return
    ruleset = json.loads(path.read_text(encoding="utf-8"))
    rules = ruleset.setdefault("rules", [])
    checks = [
        {"context": job, "integration_id": _GITHUB_ACTIONS_INTEGRATION_ID}
        for job in _CI_JOBS
    ]
    for rule in rules:
        if rule.get("type") == "required_status_checks":
            rule.setdefault("parameters", {})["required_status_checks"] = checks
            break
    else:
        rules.append(
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": False,
                    "do_not_enforce_on_create": False,
                    "required_status_checks": checks,
                },
            }
        )
    path.write_text(json.dumps(ruleset, indent=2) + "\n", encoding="utf-8")


def _substitute_manifest_name(root: Path, project_name: str) -> None:
    """Replace the manifest placeholder package name with the chosen project name.

    Both shipped manifests (`stacks/python/pyproject.toml`,
    `stacks/react/package.json`) declare a literal placeholder package name —
    `template-placeholder-project-name` — because `{{PROJECT_NAME}}` is not a
    valid PEP 508 / npm package identifier. We swap that literal here.
    """
    for rel in _MANIFEST_FILES:
        p = root / rel
        if p.exists():
            escape = _MANIFEST_FORMAT.get(rel, lambda s: s)
            text = p.read_text(encoding="utf-8")
            p.write_text(
                text.replace(_MANIFEST_PLACEHOLDER, escape(project_name)),
                encoding="utf-8",
            )


def initialize(
    root: Path | str,
    stack: str,
    project_name: str,
    description: str,
    apply_settings: bool = False,
    runner: Callable[..., object] = subprocess.run,
) -> None:
    """Collapse the template into a single-stack project rooted at ``root``."""
    root = Path(root)
    if stack not in STACKS:
        raise ValueError(f"stack must be one of {STACKS}, got {stack!r}")
    if not (root / "stacks").is_dir():
        raise RuntimeError("no stacks/ directory — repo already initialized?")
    if not (root / "stacks" / stack).is_dir():
        raise RuntimeError(f"stacks/{stack} not found")

    # 2. Promote chosen stack to root, then 3. prune.
    _promote(root, stack)
    shutil.rmtree(root / "stacks")
    other_rules = root / ".agents" / "rules" / _other(stack)
    if other_rules.is_dir():
        shutil.rmtree(other_rules)

    # 4. Rewrite generated files.
    for rel in _HTML_FILES:
        p = root / rel
        if p.exists():
            p.write_text(
                filter_html_markers(p.read_text(encoding="utf-8"), stack),
                encoding="utf-8",
            )
    for rel in _YAML_FILES:
        p = root / rel
        if p.exists():
            p.write_text(
                filter_yaml_markers(p.read_text(encoding="utf-8"), stack),
                encoding="utf-8",
            )
    readme = root / "README.md"
    if readme.exists():
        readme.write_text(
            strip_interview(readme.read_text(encoding="utf-8")), encoding="utf-8"
        )
    _rewrite_dependabot_dir(root, stack)
    _rewrite_ci_workdir(root, stack)
    _rewrite_ci_job_ids(root, stack)
    _set_required_status_checks(root)
    for rel in _FILL_ONLY:
        p = root / rel
        if p.exists():
            text = p.read_text(encoding="utf-8")
            escape = _MANIFEST_FORMAT.get(rel)
            if escape is not None:
                # Manifest (TOML/JSON): escape values so a name/description with
                # ", \, or newlines doesn't produce an invalid manifest.
                text = text.replace("{{PROJECT_NAME}}", escape(project_name)).replace(
                    "{{DESCRIPTION}}", escape(description)
                )
            else:
                text = fill_placeholders(text, project_name, description)
            p.write_text(text, encoding="utf-8")
    _substitute_manifest_name(root, project_name)

    # 5. Apply repo settings BEFORE self-destruct, so that if the apply step fails
    # or is declined the init machinery is still present and the operator has
    # recourse (e.g. re-run, or fall back to `make apply_repo_settings`). Note the
    # default `make init` path passes apply_settings=False — settings are applied by
    # the separate, idempotent `make apply_repo_settings` step (see README).
    if apply_settings:
        runner(
            [sys.executable, str(root / "scripts" / "apply_repo_settings.py")],
            check=True,
        )

    # 6. Self-destruct template-only machinery.
    to_remove = [
        root / "scripts" / "init_template.py",
        root / "tests" / "template",
    ]
    if stack == "react":
        to_remove += [
            root / "pyproject.toml",
            root / "uv.lock",
            root / ".python-version",
            root / "scripts" / "__init__.py",
        ]
    for p in to_remove:
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
    tests_dir = root / "tests"
    if tests_dir.is_dir() and not any(tests_dir.iterdir()):
        tests_dir.rmdir()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for `make init`."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack", required=True, choices=STACKS)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--description", required=True)
    # Settings are applied by the separate `make apply_repo_settings` step (idempotent,
    # confirm-gated, re-runnable) — see the README interview flow. `make init` only
    # transforms the tree. Pass --apply-settings to fold the apply into init.
    parser.add_argument("--apply-settings", action="store_true")
    args = parser.parse_args(argv)
    initialize(
        Path.cwd(),
        args.stack,
        args.project_name,
        args.description,
        apply_settings=args.apply_settings,
    )
    print(
        f"Initialized as a {args.stack} project. "
        "Run `make apply_repo_settings` to reconcile the repo's main ruleset + "
        "PR-merge prefs, then commit and push."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
