---
description: Cursor Bugbot is no longer active on this repo — never assume it can be run, triggered, or waited on.
alwaysApply: true
---

# Cursor Bugbot is not active on this repo

Cursor Bugbot is **no longer installed/enabled** here. It will not review PRs,
automatically or on request.

**How to apply:**

- **Do NOT comment `bugbot run` or `cursor review`** on PRs — nothing will respond.
- **Do NOT wait for a Bugbot check or review**, and don't conclude a PR is
  unreviewed-and-blocked because none appeared. An empty check list is expected.
- For an automated pre-merge review, use `superpowers:requesting-code-review` (or
  `/code-review`) instead; human reviewers and Copilot review (if enabled) still apply.
- `.cursor/BUGBOT.md` is retained only in case Bugbot is re-enabled; if it is, update
  this rule and the `resolve-pr-concerns` skill (Steps 1a/5) to restore trigger-mode detection.
