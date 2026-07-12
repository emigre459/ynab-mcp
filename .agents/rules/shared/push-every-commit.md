---
description: Push to the remote after every commit — a local-only branch is invisible work; the remote branch IS the in-flight signal the board tooling reads
alwaysApply: true
---

# Push every commit

**Push to `origin` immediately after every commit.** Create the remote branch (`git push -u origin <branch>`) at the FIRST commit of any piece of work, not when the PR is ready.

**Why:** a branch that lives only on one laptop is invisible work, and we now depend on remote-branch visibility in several load-bearing ways:

1. **In-flight detection** — build-from-issue's propose-next mode (Step 0) and momentum hook (Step 11b) classify an issue as in-flight from its remote branch / open PR. A local-only branch means a teammate (or another agent session) gets that issue *recommended* and starts duplicate work.
2. **Standup/reporting visibility** — standup tooling only sees pushed work; local-only commits vanish from "In flight."
3. **Crash/loss safety** — hours of un-pushed commits are one disk failure from gone.
4. **Parallel-session coordination** — multiple agent sessions ground their "what's already started" reasoning in the remote; the remote must therefore be current.

**Discipline:**
- Commit checkpoints per the checkpoint-commits rule, and push each one. Commit-then-push is ONE motion, not two phases.
- WIP state is fine to push on a feature branch — nobody expects feature-branch tips to be green; CI gates live on the PR, not the branch.
- If a push is rejected (remote moved), reconcile immediately (`git pull --no-rebase` or rebase per branch convention) — do not keep committing locally on a diverged branch.

**Exceptions (rare, deliberate, stated out loud):**
- Secrets/credentials accidentally committed — fix history BEFORE the first push (this is exactly why the rule is push-per-commit, not push-per-hour: un-pushed history is still rewritable).
- Explicitly-local throwaway spikes the user has said will never become a PR.
