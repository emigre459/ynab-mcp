---
description: main is protected — every change lands via a squash-merged PR, never a local merge. When a skill (e.g. finishing-a-development-branch) offers a "merge locally" option, that option does not apply here.
alwaysApply: true
---

# main only takes PRs — never a local merge

`main`'s branch ruleset enforces PR review-thread resolution and squash-merge —
see the "PR & Commit Guidelines" section of `AGENTS.md`. A local `git merge` into
`main` (even followed by a push) is not this repo's workflow, regardless of
whether it would technically succeed.

**Why:** `superpowers:finishing-a-development-branch` is a generic, repo-agnostic
skill — its 4-option menu ("merge locally / push + create PR / keep as-is /
discard") is written for projects with no branch-protection convention. On this
repo, "merge locally" is not a real option; presenting it at face value invites
confusion (or a rejected push) at the exact moment work is otherwise done.

**How to apply**
- When any skill's finishing/completion menu includes a "merge locally to
  `<base-branch>`" choice and `<base-branch>` is `main`, treat it as unavailable
  here — don't offer it, or if a generic skill's template forces you to render
  it, say up front that it doesn't apply to this repo and why.
- The real choices on this repo are: push + create/update a PR, keep the branch
  as-is, or discard. Every completed change reaches `main` through a PR.
- If a skill you're following (in this repo or a plugin) states or implies a
  local-merge path to `main` as viable, that's a documentation gap in the
  *calling* skill, not a reason to actually do it — fix the calling skill's text
  to point here instead of routing around the rule silently.
