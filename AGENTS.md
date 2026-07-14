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
  `YNAB_DEFAULT_BUDGET_ID` (optional), `YNAB_READ_ONLY` (parsed, unenforced
  until write tools exist). `AmazonSettings.from_env()` reads
  `AMAZON_USERNAME`/`AMAZON_PASSWORD`/`AMAZON_OTP_SECRET_KEY` — fail-**soft**
  (returns `None`, never raises), the deliberate asymmetry with `Settings`:
  Amazon integration is optional server-wide functionality.
- `client.py` — builds the single shared `ynab.ApiClient`; `resolve_budget_id`
  is the only place the public `budget_id` terminology (matches YNAB's
  product UI) translates to the SDK's internal `plan_id` (the `ynab` client
  renamed `Budget`→`Plan` in v4). Never let `plan_id` leak into a public tool
  name/param.
- `amazon_client.py` — builds the shared `AmazonSession`/`AmazonOrders`/
  `AmazonTransactions` clients when Amazon is configured. Registers
  `amazonorders.contrib.browser.playwright`'s `PlaywrightAcicForm`/
  `PlaywrightJSAuthForm` (requires the `amazon-orders[browser]` extra +
  `uv run playwright install chromium`) so real Amazon logins can clear
  JavaScript bot-detection challenges automatically. Never calls
  `.login()` itself — an MCP tool call can't handle an interactive
  challenge mid-request — but `server.py` calls it once at startup (see
  below); the persisted session from `scripts/amazon_login.py` makes that
  fast (no interactive step) in the common case.
- `amazon_matching.py` — pure, zero-I/O merge-key algorithm joining YNAB
  transactions to Amazon `Transaction` records (exact amount + date-window,
  classified exact/near-date/split-shipment/ambiguous/no-match). No
  dependency on the `ynab` or `amazon-orders` SDKs — both sides are
  pre-converted into small dataclasses by the caller, so it's fully
  fixture-testable.
- `errors.py` — `translate_api_exception` maps `ynab.ApiException` →
  `fastmcp.exceptions.ToolError`, carrying YNAB's real error detail, never
  masked. `translate_amazon_exception` does the same for
  `amazonorders.exception.AmazonOrdersError`, with a remediation hint
  pointing at `scripts/amazon_login.py` for auth-specific failures.
- `tools/` — one module per tool group, each with a plain testable function
  plus a thin `@mcp.tool`-registering `register(mcp, client, settings)`
  function (budgets.py's `register` omits `settings` — no default-budget
  concept applies to listing all budgets). `find_amazon_transactions.py`
  additionally takes the Amazon clients and reuses `tools/transactions.py`'s
  `list_transactions()` rather than re-implementing YNAB fetching.
- `server.py` — `build_server()` wires it all together; `list-budgets` is
  registered only when no default budget is configured.
  `find-amazon-transactions` is registered only when `AmazonSettings.from_env()`
  succeeds **and** `amazon_session.login()` succeeds at startup (caught and
  logged to stderr on failure, fail-soft — a broken/expired Amazon session
  never takes down the whole YNAB server). `main()` is the `uv run ynab-mcp`
  entry point (`[project.scripts]` in `pyproject.toml`).

Design rationale: `docs/superpowers/specs/2026-07-12-core-ynab-mcp-server-design.md`
(core server), `docs/superpowers/specs/2026-07-12-find-amazon-transactions-design.md`
(Amazon matching — includes several "Correction from live testing" notes worth
reading before touching this area again: a `grand_total` sign-convention gotcha,
why blank `order_number`s must still be matchable, and the login-at-startup fix).

### One-time setup for `find-amazon-transactions`

`scripts/amazon_login.py` establishes the persisted Amazon session
out-of-band (interactive; can solve JS challenges via a headless browser).
Run `uv run playwright install chromium` once per machine first. See the
script's docstring and `README.md`'s Setup section.

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
