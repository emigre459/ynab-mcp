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

### Architecture: `src/ynab_mcp/`

A FastMCP v3 stdio server wrapping the official `ynab` PyPI client. Layout,
established in issue #11 and extended by every later epic-#10 child that adds
tools:

- `config.py` — `Settings.from_env()` reads `YNAB_PAT` (required, fail-hard),
  `YNAB_DEFAULT_BUDGET_ID` (optional), `YNAB_READ_ONLY` (defaults `true`,
  enforced by every write tool via `client.require_writable`).
- `client.py` — builds the single shared `ynab.ApiClient`; `resolve_budget_id`
  is the only place the public `budget_id` terminology (matches YNAB's
  product UI) translates to the SDK's internal `plan_id` (the `ynab` client
  renamed `Budget`→`Plan` in v4). Never let `plan_id` leak into a public tool
  name/param. `require_writable(settings)` raises `ToolError` when
  `YNAB_READ_ONLY=true`; every write tool's registered closure calls it as
  its first statement, before `resolve_budget_id` and before touching the
  API — write tools are always *registered* (discoverable in both modes),
  only *execution* is gated.
- `errors.py` — `translate_api_exception` maps `ynab.ApiException` →
  `fastmcp.exceptions.ToolError`, carrying YNAB's real error detail, never
  masked.
- `tools/` — one module per tool group, each with a plain testable function
  plus a thin `@mcp.tool`-registering `register(mcp, client, settings)`
  function (budgets.py's `register` omits `settings` — no default-budget
  concept applies to listing all budgets). Write-tool modules
  (`transactions_write.py`, `budgeted_amount.py`, `payees_write.py`,
  `scheduled_transactions.py`, issue #12) additionally give each registered
  closure its own required-field validation and a `fastmcp.Client`-based
  closure-dispatch test — the underlying plain function alone doesn't
  exercise that branching.
  - **`transactions_write.py`'s `bulk_manage_transactions` update path
    cannot use `TransactionsApi.update_transactions()`.** The installed
    `ynab` SDK (v4.2.0, latest on PyPI) has a real bug: its generated
    `_response_types_map` for that endpoint keys off HTTP `209` instead of
    the `200` YNAB actually returns, so the convenience method silently
    returns `None` on every real, successful call. The fix uses
    `update_transactions_with_http_info()` and parses `raw_data` directly
    with `ynab.SaveTransactionsResponse.model_validate_json(...)`,
    bypassing the broken status-code dispatch. Reported upstream:
    [ynab/ynab-sdk-python#33](https://github.com/ynab/ynab-sdk-python/issues/33)
    ([fix PR](https://github.com/ynab/ynab-sdk-python/pull/34)) — if/when a
    corrected SDK version ships, this workaround can likely be reverted to
    the plain convenience method (confirm the fix landed before doing so).
- `server.py` — `build_server()` wires it all together; `list-budgets` is
  registered only when no default budget is configured; all four write
  tools are always registered (see `client.require_writable` above).
  `main()` is the `uv run ynab-mcp` entry point (`[project.scripts]` in
  `pyproject.toml`).

Design rationale: `docs/superpowers/specs/2026-07-12-core-ynab-mcp-server-design.md`
(read tools), `docs/superpowers/specs/2026-07-12-transaction-budget-write-tools-design.md`
(write tools).

## Quality Gates

Every change must pass `make pr_check` (lint + tests) before a PR is opened.

| Command | What it runs |
|---------|--------------|
| `make deps` | Install dependencies |
| `make format` | Auto-format the source tree |
| `make lint` | Format-check + lint + type-check |
| `make tests` | Unit tests |
| `make e2e` | E2E tests (spawns the real `uv run ynab-mcp` stdio subprocess) |
| `make run` | Run the YNAB MCP stdio server (needs a real `YNAB_PAT` in `.env`) |
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
