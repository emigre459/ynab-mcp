# AI Agent Instructions — ynab-mcp

> This file is the single source of truth for AI assistants working in this repository.
> Shared cross-cutting rules live in `.agents/rules/` and are NOT duplicated here — treat them as authoritative for their declared scopes.

---

## Rules (read these; do not override them)

All shared, cross-cutting rules live in **`.agents/rules/`** — a platform-agnostic
directory that every coding agent (Claude Code, Cursor, …) must read and follow.
This is our team rule-sharing mechanism: durable conventions belong here, not in
any one developer's local agent memory. See `.agents/rules/shared/default-to-shareable-rules.md`.

Each rule is a Markdown file with frontmatter:
- `description` — one line; use it to judge whether the rule is relevant.
- `appliesTo` — optional glob hint. Map it to your own tool's mechanism (Cursor
  auto-attach `globs:`, Claude Code "load when working on matching files"). When
  absent or `alwaysApply: true`, the rule is relevant to every task.

| File | Applies to | Summary |
|------|-----------|---------|
| `.agents/rules/shared/push-every-commit.md` | always | Push to origin after EVERY commit (`-u` on the first) — the remote branch is the in-flight signal build-from-issue Step 0/11b and parallel sessions read |
| `.agents/rules/shared/*.md` | always / varies | Git, commit, issue-workflow, and meta conventions — read the directory |
| `.agents/rules/python/uv-python.md` | always | Use `uv` for all Python execution and dependency management |
| `.agents/rules/python/python-best-practices.md` | `**/*.py` | Style, type hints, TDD, API design, docstrings |
| `.agents/rules/python/*.md` (others) | varies | dotenv loading, library-vs-scripts structure |

## Project Overview

MCP server for YNAB

This is a **Python backend** project managed with `uv`. Source lives in `src/`,
tests in `tests/`. All quality gates run through the `Makefile`.

## Quality Gates

Every change must pass `make pr_check` (lint + tests) before a PR is opened.

| Command | What it runs |
|---------|--------------|
| `make deps` | Install dependencies |
| `make format` | Auto-format the source tree |
| `make lint` | Format-check + lint + type-check |
| `make tests` | Unit tests |
| `make coverage` | Tests with an 80% coverage gate |
| `make security` | Dependency / SAST scan |
| `make pr_check` | `lint` + `tests` |
| `make cc` | Launch Claude Code with this repo's settings |

## Skills

Reusable agent workflows live in `.agents/skills/` (canonical). Claude Code reads
them through the `.claude/skills` symlink; Cursor reads `.agents/skills/` natively.
When writing or editing a skill, keep it harness-agnostic — see
`.agents/rules/shared/harness-agnostic-skills.md` (canonical paths, skill-root-relative
bundled files, and which `SKILL.md` frontmatter is portable vs Claude-Code-only).

## Hooks

`.claude/hooks/run-tests-on-stop.sh` formats and runs tests when source files change
in a turn. `.claude/hooks/claude_permission_hook.sh` forwards pre-approved Bash
permissions to subagents.

## PR & Commit Guidelines

- Reference the issue in the PR body (`Closes #N`).
- Checkpoint-commit per logical slice (see `.agents/rules/shared/checkpoint-commits.md`).
- Squash-merge only; the `main` ruleset enforces PR review-thread resolution.

## Where LLM instructions live

`CLAUDE.md` imports this file so its contents load into every Claude Code session.
Shared rules live in `.agents/rules/` and are routed from the `## Rules` section
above. Skills live in `.agents/skills/`.
