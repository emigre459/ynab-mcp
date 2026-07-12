# agentic-ai-powered-repo

A Gridium template repo that seeds new repos with our AI-powered development best
practices — CI/CD, testing, agent rules/skills, and repo settings — for either a
Python backend or a React + TypeScript frontend.

<!-- INTERVIEW:start -->
## Start here: initialize this template

Paste the prompt below into your agentic coding harness (Claude Code, Cursor, …).
It interviews you about the repo you're building, then runs `make init`,
reconciles this repo's `main` branch protection + PR-merge settings, and opens
a PR with the init commit (the reconciled settings make `main` PR-only).

```text
You are initializing a new repository created from Gridium's
agentic-ai-powered-repo template. Drive this end to end.

FIRST: use your harness's native structured-interview tool if you have one
(e.g. Claude Code's AskUserQuestion, Cursor's equivalent) to ask the questions
below — these are easier to answer than free-form text. Only fall back to plain
chat questions if no such tool exists. Ask ONE question at a time.

Interview:
1. Is this a FRONTEND or BACKEND repo?
2. Confirm the stack, seeded with Gridium org defaults:
   - Backend default: Python 3.13 + uv (black, ruff, mypy, pytest, bandit).
   - Frontend default: Vite + React + TypeScript + bun
     (Biome [Gridium snapmeter formatting], Vitest, tsc).
   The two shipped stacks are the only supported choices today; other
   languages/frameworks are a future template extension.
3. What is the project NAME (short, kebab-case) and a ONE-LINE description?
4. Confirm the target GitHub repo for settings reconciliation is THIS repo
   (show them `gh repo view --json nameWithOwner -q .nameWithOwner`).

THEN run, in order:
- Create a "project setup" issue and a linked working branch FIRST — all
  changes reach `main` via PR (the settings step below makes `main` PR-only,
  so a direct push would be rejected):
    - `gh issue create --title "Project setup: initialize from agentic-ai-powered-repo template" --body "..."`
      (brief bullet-checklist body; if the repo already has epics on its board,
      parent the issue under the one that fits — otherwise standalone is fine
      for this one-time bootstrap).
    - `gh issue develop <N> --name chore/<N>-project-setup --base main --checkout`
- `make init STACK=<python|react> PROJECT_NAME="<name>" DESCRIPTION="<desc>"`
  (this promotes the chosen stack to root, prunes the other, and removes the
  template machinery).
- `make apply_repo_settings` (it prints a diff of this repo's main ruleset +
  PR-merge prefs vs the canonical settings and asks you to confirm before
  applying; if your shell can't answer its interactive prompt, confirm with the
  user via your interview tool, then re-run with `--yes`).
- Stage everything and commit on the branch:
  `git add -A && git commit -m "chore: initialize from agentic-ai-powered-repo template"`.
- Run `make deps && make pr_check` yourself to confirm the stack is green
  (fix anything red before proceeding).
- Push the branch and open a PR to main that closes the issue:
  `git push -u origin HEAD && gh pr create --fill --body "Closes #<N>"`
  (follow the repo's PR template). Tell the user to review and squash-merge it.
- Tell the user that automated PR review (Cursor Bugbot) may need to be enabled
  on this new repo — it is configured per-repo, not inherited from the template.
  Two steps:
    1. Install/approve the Cursor GitHub App for the repo (request access, or
       approve if you're a GitHub org admin):
       https://github.com/apps/cursor/installations/74220607
    2. Enable the repo on the Cursor side:
       https://cursor.com/dashboard/bugbot/installation/74220607
  Once enabled, Bugbot reviews automatically on each push (no `bugbot run`
  comment needed).

Do not invent settings or skip the confirmation prompts.
```
<!-- INTERVIEW:end -->

## What this template provides

- **Dual stacks** under `stacks/python` and `stacks/react`, each runnable and
  CI-green out of the box; `make init` collapses to the one you choose.
- **Shared agent infra:** `AGENTS.md` (single source of truth) routing to
  `.agents/rules/`, plus harness-agnostic skills in `.agents/skills/` (Claude Code
  reads them via the `.claude/skills` symlink; Cursor natively).
- **`Makefile` orchestration** with identical verbs across stacks
  (`make deps|format|lint|tests|coverage|security|pr_check`) and `make cc` to drive
  Claude Code.
- **Canonical repo settings** in `.github/repo-settings/`, applied via
  `make apply_repo_settings`.

## Prerequisites

| To… | You need |
|-----|----------|
| Initialize the template (`make init`) + apply repo settings (`make apply_repo_settings`) | `git`, `gh`, and **`python3`** (standard on macOS/Linux). **No `uv` required** — the init/apply scripts are stdlib-only and run under bare `python3`. |
| Work in a **React** repo (after init) | **`bun`** only — no Python toolchain at all. |
| Work in a **Python** repo (after init) | **`uv`** (Python 3.13). |
| Hack on the **template itself** (run `tests/template`, `make machinery_*`) | `uv` — the machinery's own test suite uses pytest. (Template maintainers only; not template *users*.) |

So a frontend-only developer can take this template, run `make init STACK=react`,
and from then on never touch Python or `uv` — the one-time `make init`/`make
apply_repo_settings` calls use `python3`, which is already present.

See `docs/superpowers/specs/2026-06-09-cicd-testing-template-design.md` for the design.
