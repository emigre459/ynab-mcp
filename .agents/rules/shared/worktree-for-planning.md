---
description: For gh-heavy / code-light planning work (epics, issue triage, kanban cleanup), switch into a worktree off main first; if already in one, verify main is current.
alwaysApply: true
---

# Worktree for planning sessions

When the work is clearly project planning — building epics, triaging issues,
cleaning the kanban, organizing labels/milestones (anything `gh`-heavy and
code-light) — set up an isolated worktree off `main` before substantive work.

**Why:** Coding agents may be running in parallel on the same repo. Planning on
the same checkout risks disturbing their working tree, triggers Stop hooks (e.g.
`make tests`) that fail noisily against a half-finished branch, and bases
judgement on possibly-stale code. A worktree off main fixes all three.

**How to apply**
- Trigger phrases: "build an epic", "clean up the kanban", "triage issues",
  "organize", "plan out", "wrap X into an epic".
- Not in a worktree: use the worktree tooling (`EnterWorktree` or the
  `superpowers:using-git-worktrees` skill) with a planning-themed name; it branches
  from `origin/<default-branch>` by default.
- Already in a worktree: `git fetch origin && git log --oneline HEAD..origin/main`;
  if main advanced, bring it current (`git merge origin/main`, or
  `git reset --hard origin/main` only if there are no local commits — confirm
  before destructive moves).
- Light code work inside the worktree is fine; don't push commits from a planning
  worktree without telling the user.
- Skip only if the user says "stay on this branch" or the work genuinely needs the
  feature branch's code.
