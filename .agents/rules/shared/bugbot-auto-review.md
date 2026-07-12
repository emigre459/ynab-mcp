---
description: How Cursor Bugbot is triggered on PRs, and how that interacts with the explicit `bugbot run` re-trigger in resolve-pr-concerns.
alwaysApply: true
---

# Cursor Bugbot triggering on PRs

Cursor Bugbot's trigger behavior is a **per-repo setting** in the Cursor dashboard,
not something this repo controls:

- **Automatic mode** — Bugbot reviews on every PR create/update (push).
- **Manual mode** — Bugbot reviews only when someone comments `bugbot run` (or
  `cursor review`) on the PR.

Bugbot must also be **installed** (the Cursor GitHub App) and **enabled** for the
repo before it reviews at all. A fresh repo created from this template has no Bugbot
review until someone installs + enables it.

**How to apply:** Detect the mode once per PR (see `resolve-pr-concerns` Step 1a)
and act accordingly:

- **Automatic mode (the Gridium default once Cursor is installed):** the push
  already triggered a fresh review. **Do NOT comment `bugbot run`** — it's a
  redundant double-trigger that just clutters the PR. Wait for the auto-review.
- **Manual mode:** comment `bugbot run` after pushing fixes, since nothing else
  will trigger a re-review.

Don't blindly comment `bugbot run` "to be safe" — on an auto-on-push repo that
double-triggers every round. Confirm the mode first, then skip or send accordingly.
