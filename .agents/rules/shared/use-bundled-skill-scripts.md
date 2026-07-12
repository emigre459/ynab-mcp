---
description: When a skill ships a script, run it. Don't substitute a manual approach because it looks slow — investigate first (often a pending permission prompt).
alwaysApply: true
---

# Use the skill's bundled script

When a skill provides a bundled script (e.g. `changelog/scripts/changelog.py`,
`resolve-pr-concerns/scripts/wait_for_pr_checks.sh`), **run it.** Don't substitute
a manual git-log / shell-cobbled version.

**Why:** The skill ships a tested script for a reason; a manual substitute is your
approximation, not the canonical output, and forces the user to mentally diff the
two. A script that "appears to hang" is often waiting on a permission prompt, not
broken.

**How to apply**
1. Run the canonical command from the skill's `SKILL.md` verbatim (adapt
   `python3` → `uv run python` per `uv-python.md`).
2. If it seems stuck, don't assume failure: a permission prompt may be pending, or
   it may be doing real work. Use `run_in_background: true` for long scripts and
   read output progressively; check process state before declaring failure.
3. If it genuinely fails, debug the root cause and re-run — don't replace it.
4. If you have a real reason to bypass (corrupt skill, env mismatch), say so
   explicitly and ask the user before substituting.
