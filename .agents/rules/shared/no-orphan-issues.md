---
description: Before gh issue create, fit the new issue under an existing epic; if none fits, propose an epic before creating. Avoid orphan issues.
alwaysApply: true
---

# No orphan issues

Before `gh issue create`, check the open epics. A new issue should land as a child
of an existing epic if it plausibly fits, or trigger a brief "what epic would this
go in?" conversation if it doesn't.

**Why:** Orphan issues accumulate, lose context, and don't get worked
systematically. Epics give thematic organization, GH-native parent-child links,
blocked-by dependencies, and execution order.

**How to apply**
- Before creating: `gh issue list --label epic` (or GraphQL for issues with
  non-empty `subIssues.nodes`); skim the epic set.
- Fits an epic: set parent via the GraphQL `addSubIssue` mutation right after
  create, and reference the epic in the body.
- No epic fits: surface it to the user *before* creating — new epic? fold into an
  existing one with a stretch interpretation? accept an orphan for now?
- Trivial standalone bugfixes: a quick sanity check is enough; an orphan is
  acceptable for tiny, immediately-actionable items. The rule is "try to fit," not
  "always parent."

See `gh-issue-dependencies.md` and `worktree-for-planning.md`.
