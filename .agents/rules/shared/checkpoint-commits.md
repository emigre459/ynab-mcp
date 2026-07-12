---
description: For multi-dimensional tasks, commit after each logical slice passes — never batch into one giant end-of-session commit.
alwaysApply: true
---

# Checkpoint commits per slice

On any multi-dimensional task — especially `/build-from-issue` or work with TODO
checkboxes / sub-tasks — commit after each logical dimension is implemented and
its tests pass. Do **not** save up one giant end-of-session commit.

**Why:** Batching produces unreviewable history. Marking a task "completed" in
tracking is not the same as committing.

**How to apply**
- Commit when a slice compiles, tests, and stands on its own — before moving on.
- Treat finishing a task/checkbox as a paired prompt to `git commit`.
- 6–10 commits in one session is the goal, not a smell.
- Pair TDD tests with their implementation in the same commit so each commit
  leaves the repo green.
- Batching is acceptable only for a trivial single-dimension task (one file, one
  fix). Never `git add -A && git commit` at the end of a long multi-dimension session.
