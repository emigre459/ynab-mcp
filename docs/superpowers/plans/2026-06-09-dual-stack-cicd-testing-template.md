# Dual-Stack CI/CD + Testing Template Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `agentic-ai-powered-repo` into a Gridium template that carries both a Python/`uv` backend stack and a Vite+React+TS/`bun` frontend stack, each runnable green out of the box, with `make init` pruning to the chosen stack and a README interview prompt that also reconciles the new repo's `main` ruleset + PR-merge settings.

**Architecture:** Stack-isolated subdirectories (`stacks/python`, `stacks/react`) coexist pre-init; shared agent infra (`AGENTS.md` router → `.agents/rules`, `.agents/skills` + one `.claude/skills` symlink) lives at root; `make init STACK=…` promotes the chosen stack to root and prunes the rest via deterministic, marker-driven text transforms; `.github/repo-settings/` holds the canonical ruleset + merge prefs that `apply_repo_settings.py` diff-applies via `gh`.

**Tech Stack:** Python 3.13 / uv / black / ruff / mypy / pytest / bandit; React 19 / Vite / TypeScript / bun / Biome / Vitest; GNU Make; GitHub Actions; `gh` CLI.

**Reference repos (read-only):** `~/Documents/Projects/gridium-agent` (`origin/main`) for backend + agent infra; `Gridium/snapmeter` (`main`, via `gh`) for frontend formatting. Run `git -C ~/Documents/Projects/gridium-agent fetch origin main` once before starting.

---

## Conventions used throughout this plan

- **Marker comments** make generated dual-stack files prunable by `init_template.py`:
  - Markdown/HTML files (`AGENTS.md`, `README.md`): `<!-- STACK:python -->` … `<!-- /STACK:python -->`, `<!-- STACK:react -->` … `<!-- /STACK:react -->`, and `<!-- INTERVIEW:start -->` … `<!-- INTERVIEW:end -->`.
  - YAML files (`ci.yml`, `dependabot.yml`): `# >>> STACK:python` … `# <<< STACK:python` (and `react`).
  - Placeholders `{{PROJECT_NAME}}` and `{{DESCRIPTION}}` are filled at init.
- **Implementation decision (refines spec):** kept-stack rules stay in their `.agents/rules/<stack>/` subdir post-init (the other subdir is deleted). We do **not** flatten — this avoids rewriting rule paths in `AGENTS.md`; the stack-marker filter already removes the other stack's routing rows.
- **`mk/shared.mk` is included via the git root** so each stack Makefile works whether it sits in `stacks/<stack>/` or (post-init) at root — no include-path rewrite needed:
  ```makefile
  REPO_ROOT := $(shell git rev-parse --show-toplevel)
  include $(REPO_ROOT)/mk/shared.mk
  ```
- Commit after every task. Use `git mv`/`git rm` so staging stays clean.

---

## Task 1: Root tooling env + repo hygiene

**Files:**
- Create: `pyproject.toml` (root template-tooling only)
- Create: `.python-version`
- Create: `.gitignore`
- Delete: `Makefile` (broken gridium-agent copy — replaced in Task 14)
- Delete: `.claude/scripts/sync-shared-skill.sh` (dropped machinery)

- [ ] **Step 1: Remove broken/dropped files**

```bash
git rm Makefile .claude/scripts/sync-shared-skill.sh
rmdir .claude/scripts 2>/dev/null || true
```

- [ ] **Step 2: Create `.python-version`**

```
3.13.5
```

- [ ] **Step 3: Create root `pyproject.toml`** (tooling only — runs the machinery tests in `tests/template/`; stdlib scripts need no runtime deps)

```toml
[project]
name = "agentic-ai-powered-repo-tooling"
version = "0.0.0"
description = "Template-only tooling: tests for the init/apply machinery. Removed or replaced at `make init`."
requires-python = "==3.13.5"
dependencies = []

[dependency-groups]
dev = [
    "black>=26.3.0",
    "ruff>=0.14.0",
    "mypy>=1.13.0",
    "pytest>=9.0.0",
    "pytest-xdist>=3.6.1",
]

[tool.black]
line-length = 88

[tool.ruff]
line-length = 88
target-version = "py313"

[tool.ruff.lint]
extend-select = ["E501", "W", "D"]
extend-ignore = ["D107"]

[tool.ruff.lint.pydocstyle]
convention = "numpy"

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["E501", "D100", "D101", "D102", "D103", "D104"]
"scripts/**" = ["E402", "E501", "D100"]

[tool.mypy]
python_version = "3.13"
files = ["scripts", "tests"]
ignore_missing_imports = true
show_error_codes = true
disallow_untyped_defs = true

[tool.pytest.ini_options]
testpaths = ["tests/template"]
addopts = "-n auto"
```

- [ ] **Step 4: Create `.gitignore`** (generic essentials, ported subset of gridium-agent's)

```gitignore
# Python
*.pyc
__pycache__/
.venv/
.coverage
.coverage.*
htmlcov/
coverage.xml

# Node / bun
node_modules/
dist/
bun.lockb
*.local

# Env / secrets
.env

# OS / editor
.DS_Store

# Claude Code
.claude/worktrees/
.claude/settings.local.json

# Local scratch
local/
```

- [ ] **Step 5: Verify uv resolves the tooling env**

Run: `uv sync --dev`
Expected: resolves and installs black/ruff/mypy/pytest into `.venv` with no error.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: root tooling env + gitignore; drop broken Makefile and skill-sync script"
```

---

## Task 2: Shared agent rules (`.agents/rules/shared/`)

**Files (create, ported verbatim from gridium-agent `origin/main:.agentrules/`):**
- `.agents/rules/shared/default-to-shareable-rules.md`
- `.agents/rules/shared/checkpoint-commits.md`
- `.agents/rules/shared/never-delete-only-close.md`
- `.agents/rules/shared/no-orphan-issues.md`
- `.agents/rules/shared/issue-card-brevity.md`
- `.agents/rules/shared/gh-issue-dependencies.md`
- `.agents/rules/shared/worktree-for-planning.md`
- `.agents/rules/shared/bugbot-auto-review.md`
- `.agents/rules/shared/fetch-library-docs-first.md`
- `.agents/rules/shared/fail-hard-not-warn.md`
- `.agents/rules/shared/use-bundled-skill-scripts.md`

- [ ] **Step 1: Copy the shared rule files from gridium-agent**

```bash
mkdir -p .agents/rules/shared
G=~/Documents/Projects/gridium-agent
for f in default-to-shareable-rules checkpoint-commits never-delete-only-close \
         no-orphan-issues issue-card-brevity gh-issue-dependencies \
         worktree-for-planning bugbot-auto-review fetch-library-docs-first \
         fail-hard-not-warn use-bundled-skill-scripts; do
  git -C "$G" show "origin/main:.agentrules/$f.md" > ".agents/rules/shared/$f.md"
done
```

- [ ] **Step 2: Rename the dir self-references `.agentrules/` → `.agents/rules/`**

Only `default-to-shareable-rules.md` mentions the old path. Apply:

```bash
sed -i '' 's#\.agentrules/#.agents/rules/#g' .agents/rules/shared/default-to-shareable-rules.md
```

- [ ] **Step 3: Verify no stale path references remain**

Run: `grep -rn 'agentrules' .agents/rules/shared/ || echo "clean"`
Expected: `clean`

- [ ] **Step 4: Verify each file has YAML frontmatter**

Run: `for f in .agents/rules/shared/*.md; do head -1 "$f" | grep -q '^---$' && echo "$f ok" || echo "$f BAD"; done`
Expected: every line ends in `ok`

- [ ] **Step 5: Commit**

```bash
git add .agents/rules/shared
git commit -m "feat: shared agent rules in .agents/rules/shared (ported from gridium-agent)"
```

---

## Task 3: Python stack rules (`.agents/rules/python/`)

**Files (create, ported from gridium-agent `origin/main:.agentrules/`):**
- `.agents/rules/python/uv-python.md`
- `.agents/rules/python/python-best-practices.md`
- `.agents/rules/python/load-dotenv-first.md`
- `.agents/rules/python/library-vs-scripts.md`

- [ ] **Step 1: Copy the python rule files**

```bash
mkdir -p .agents/rules/python
G=~/Documents/Projects/gridium-agent
for f in uv-python python-best-practices load-dotenv-first library-vs-scripts; do
  git -C "$G" show "origin/main:.agentrules/$f.md" > ".agents/rules/python/$f.md"
done
```

- [ ] **Step 2: Strip gridium-agent-specific references**

Open `.agents/rules/python/python-best-practices.md` and `library-vs-scripts.md`; replace any literal `gridium_agent` / `src/gridium_agent` references with the generic `src/<your_package>`. Replace any `.agentrules/` with `.agents/rules/`.

```bash
sed -i '' -e 's#src/gridium_agent#src/<your_package>#g' -e 's#gridium_agent#<your_package>#g' -e 's#\.agentrules/#.agents/rules/#g' .agents/rules/python/*.md
```

- [ ] **Step 3: Verify clean**

Run: `grep -rn 'gridium_agent\|agentrules' .agents/rules/python/ || echo "clean"`
Expected: `clean`

- [ ] **Step 4: Commit**

```bash
git add .agents/rules/python
git commit -m "feat: python agent rules in .agents/rules/python (ported + genericized)"
```

---

## Task 4: React stack rules (`.agents/rules/react/`) — NEW

**Files:**
- Create: `.agents/rules/react/bun-react.md`
- Create: `.agents/rules/react/react-best-practices.md`

- [ ] **Step 1: Create `.agents/rules/react/bun-react.md`**

```markdown
---
description: Use bun for all JS/TS execution and dependency management in this repo — never npm, yarn, or pnpm
alwaysApply: true
---

# JavaScript/TypeScript and Dependencies: Use bun

All JS/TS execution and dependency management in this project must use **bun**. Do
not use `npm`, `yarn`, or `pnpm`.

## Dependency management

- **Add a package**: `bun add <pkg>` (dev: `bun add -d <pkg>`)
- **Remove a package**: `bun remove <pkg>`
- **Install from lockfile**: `bun install`

## Running tools and scripts

- **Run a package.json script**: `bun run <script>` (e.g. `bun run build`)
- **Run a binary from node_modules**: `bunx <tool>` (e.g. `bunx vitest run`, `bunx biome check .`)
- **Run a TS/JS file directly**: `bun <file>`

## Examples

```bash
# ✅ Add dependency and run dev server
bun add zod
bun run dev

# ✅ Lint + test
bunx biome check .
bunx vitest run
```

Do not suggest or use `npm install`, `yarn`, or `pnpm` unless the user explicitly requests an exception.
```

- [ ] **Step 2: Create `.agents/rules/react/react-best-practices.md`**

```markdown
---
description: Code style, type safety, component structure, and testing conventions for the React + TypeScript stack
appliesTo: "**/*.{ts,tsx}"
---

# React + TypeScript best practices

## Tooling (run via the Makefile)

- **Format + lint:** Biome (`make lint` / `make format`). Biome is configured to match
  Gridium's existing Prettier output: single quotes, semicolons, trailing commas
  everywhere, 2-space indent, 80-col width, always-parenthesized arrow params.
- **Types:** `tsc --noEmit` (strict mode) is part of `make lint`. No `any` without a
  written justification; prefer `unknown` + narrowing.
- **Tests:** Vitest + Testing Library (`make tests`). Test user-visible behavior via
  the DOM, not implementation details. Coverage gate is 80% (`make coverage`).

## Components

- Function components only; no class components.
- One component per file. Component files are **PascalCase** (`Button.tsx`); their
  colocated tests are `Button.test.tsx`.
- Hooks rules: call hooks unconditionally at the top level; custom hooks are
  `useFoo`-named and live next to their consumer or in `src/hooks/`.
- Keep components small and focused; lift shared logic into hooks or `src/lib/`.

## Imports & structure

- Use ES module imports. Prefer named exports; default-export only the component a
  file is named for.
- Co-locate component, styles, and test. Split by feature, not by technical layer.

## Error handling

- Fail loud in development: throw on programmer errors; do not silently swallow.
- User-facing async failures surface through error boundaries / explicit UI states,
  never an empty catch.
```

- [ ] **Step 3: Verify frontmatter**

Run: `for f in .agents/rules/react/*.md; do head -1 "$f" | grep -q '^---$' && echo "$f ok" || echo "$f BAD"; done`
Expected: both `ok`

- [ ] **Step 4: Commit**

```bash
git add .agents/rules/react
git commit -m "feat: react agent rules in .agents/rules/react (new Gridium frontend conventions)"
```

---

## Task 5: Relocate skills to `.agents/skills/` + single `.claude/skills` symlink

**Files:**
- Move: `.claude/skills/{build-from-issue,plan-issues,pr-check,resolve-pr-concerns,review-skill}` → `.agents/skills/`
- Create: `.agents/skills/run-tests/` (ported from gridium-agent)
- Replace: `.claude/skills/` (real dir) → `.claude/skills` symlink to `../.agents/skills`

- [ ] **Step 1: Move existing skills to the canonical dir**

```bash
mkdir -p .agents/skills
for s in build-from-issue plan-issues pr-check resolve-pr-concerns review-skill; do
  git mv ".claude/skills/$s" ".agents/skills/$s"
done
```

- [ ] **Step 2: Port the `run-tests` skill from gridium-agent**

```bash
G=~/Documents/Projects/gridium-agent
mkdir -p .agents/skills/run-tests
git -C "$G" show "origin/main:.claude/skills/run-tests/SKILL.md" > .agents/skills/run-tests/SKILL.md
```

- [ ] **Step 3: Remove the now-empty real `.claude/skills` dir and create the symlink**

```bash
rm -rf .claude/skills
ln -s ../.agents/skills .claude/skills
```

- [ ] **Step 4: Verify the symlink resolves and skills are visible through it**

Run: `readlink .claude/skills && ls .claude/skills/`
Expected: prints `../.agents/skills` then lists `build-from-issue plan-issues pr-check resolve-pr-concerns review-skill run-tests`

- [ ] **Step 5: Verify git tracks the symlink as a symlink (mode 120000)**

Run: `git add .claude/skills && git ls-files -s .claude/skills`
Expected: a single entry beginning `120000`

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: canonical .agents/skills + single .claude/skills symlink (drop conf-driven sync)"
```

---

## Task 6: AGENTS.md dual-stack router + CLAUDE.md + .cursor + .mcp.json

**Files:**
- Create: `AGENTS.md`
- Create: `CLAUDE.md`
- Create: `.cursor/settings.json`
- Create: `.mcp.json`

- [ ] **Step 1: Create `CLAUDE.md`**

```markdown
# Claude Code — entry point

This repo's canonical AI-agent instructions live in `AGENTS.md` (the single
source of truth, read by Cursor natively and imported here for Claude Code).

@AGENTS.md
```

- [ ] **Step 2: Create `.cursor/settings.json`**

```json
{}
```

- [ ] **Step 3: Create `.mcp.json`** (minimal default — no servers preconfigured)

```json
{
  "mcpServers": {}
}
```

- [ ] **Step 4: Create `AGENTS.md`** (dual-stack, marker-wrapped so `make init` can collapse it)

````markdown
# AI Agent Instructions — {{PROJECT_NAME}}

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
| `.agents/rules/shared/*.md` | always / varies | Git, commit, issue-workflow, and meta conventions — read the directory |
<!-- STACK:python -->
| `.agents/rules/python/uv-python.md` | always | Use `uv` for all Python execution and dependency management |
| `.agents/rules/python/python-best-practices.md` | `**/*.py` | Style, type hints, TDD, API design, docstrings |
| `.agents/rules/python/*.md` (others) | varies | dotenv loading, library-vs-scripts structure |
<!-- /STACK:python -->
<!-- STACK:react -->
| `.agents/rules/react/bun-react.md` | always | Use `bun` for all JS/TS execution and dependency management |
| `.agents/rules/react/react-best-practices.md` | `**/*.{ts,tsx}` | Components, hooks, Biome/Vitest/tsc conventions |
<!-- /STACK:react -->

## Project Overview

{{DESCRIPTION}}

<!-- STACK:python -->
This is a **Python backend** project managed with `uv`. Source lives in `src/`,
tests in `tests/`. All quality gates run through the `Makefile`.
<!-- /STACK:python -->
<!-- STACK:react -->
This is a **React + TypeScript frontend** project built with Vite and managed with
`bun`. Source lives in `src/`. All quality gates run through the `Makefile`.
<!-- /STACK:react -->

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
````

- [ ] **Step 5: Verify markers are balanced**

Run:
```bash
for s in python react; do
  o=$(grep -c "<!-- STACK:$s -->" AGENTS.md); c=$(grep -c "<!-- /STACK:$s -->" AGENTS.md)
  [ "$o" = "$c" ] && echo "$s balanced ($o)" || echo "$s UNBALANCED ($o/$c)"
done
```
Expected: `python balanced (2)` and `react balanced (2)`

- [ ] **Step 6: Commit**

```bash
git add AGENTS.md CLAUDE.md .cursor/settings.json .mcp.json
git commit -m "feat: AGENTS.md dual-stack router + CLAUDE.md import + cursor/mcp config"
```

---

## Task 7: Claude Code hooks + settings.json

**Files:**
- Create: `.claude/hooks/claude_permission_hook.sh` (ported verbatim)
- Create: `.claude/hooks/run-tests-on-stop.sh` (new, stack-aware self-detecting)
- Create: `.claude/settings.json` (trimmed)

- [ ] **Step 1: Port the permission hook verbatim**

```bash
G=~/Documents/Projects/gridium-agent
git -C "$G" show "origin/main:.claude/hooks/claude_permission_hook.sh" > .claude/hooks/claude_permission_hook.sh
chmod +x .claude/hooks/claude_permission_hook.sh
```

- [ ] **Step 2: Create the stack-aware `.claude/hooks/run-tests-on-stop.sh`**

It self-detects the active stack (no init rewrite needed): pre-init `stacks/` exists → run template-machinery tests; post-init root has `package.json` → react; else python.

```bash
#!/bin/bash
# Hook: runs at the end of every Claude turn.
# Formats + runs tests for whichever stack is active, only when relevant
# source files changed this session.

cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

changed=$(
  {
    git diff --name-only HEAD 2>/dev/null
    git diff --name-only --cached 2>/dev/null
    git ls-files --others --exclude-standard 2>/dev/null
  } | sort -u
)
[ -z "$changed" ] && exit 0

run_gate() { # $1 = subdir ("" for root), $2 = grep pattern
  echo "$changed" | grep -qE "$2" || return 0
  echo "Source changed — formatting and running tests..."
  if [ -n "$1" ]; then make -C "$1" format && make -C "$1" tests || return 1
  else make format && make tests || return 1; fi
}

if [ -d stacks ]; then
  # Pre-init template repo: exercise both stacks + machinery as relevant.
  rc=0
  run_gate "stacks/python" '^stacks/python/.*\.py$' || rc=2
  run_gate "stacks/react" '^stacks/react/.*\.(ts|tsx)$' || rc=2
  if echo "$changed" | grep -qE '^(scripts|tests/template)/'; then
    uv run pytest tests/template -q || rc=2
  fi
  exit $rc
elif [ -f package.json ]; then
  run_gate "" '\.(ts|tsx)$' || exit 2
else
  run_gate "" '\.py$' || exit 2
fi
exit 0
```

```bash
chmod +x .claude/hooks/run-tests-on-stop.sh
```

- [ ] **Step 3: Create `.claude/settings.json`** (trimmed to template-relevant permissions)

```json
{
  "hooks": {
    "Stop": [
      { "hooks": [ { "type": "command", "command": "bash .claude/hooks/run-tests-on-stop.sh" } ] }
    ],
    "PreToolUse": [
      { "matcher": "Bash", "hooks": [ { "type": "command", "command": "bash .claude/hooks/claude_permission_hook.sh" } ] }
    ]
  },
  "permissions": {
    "allow": [
      "Read",
      "Bash(make help)",
      "Bash(make deps)",
      "Bash(make lint)",
      "Bash(make tests)",
      "Bash(make format)",
      "Bash(make coverage)",
      "Bash(make security)",
      "Bash(make pr_check)",
      "Bash(make init *)",
      "Bash(make apply_repo_settings)",
      "Bash(uv sync *)",
      "Bash(uv run *)",
      "Bash(bun install)",
      "Bash(bun run *)",
      "Bash(bunx *)",
      "Bash(git add *)",
      "Bash(git commit *)",
      "Bash(gh issue view *)",
      "Bash(gh pr view *)"
    ]
  }
}
```

- [ ] **Step 4: Verify JSON is valid**

Run: `python3 -c "import json; json.load(open('.claude/settings.json')); print('valid')"`
Expected: `valid`

- [ ] **Step 5: Commit**

```bash
git add .claude/hooks .claude/settings.json
git commit -m "feat: stack-aware Stop hook + permission hook + trimmed settings.json"
```

---

## Task 8: Shared make targets (`mk/shared.mk`)

**Files:**
- Create: `mk/shared.mk`

- [ ] **Step 1: Create `mk/shared.mk`** (targets that survive init: help, cc, apply_repo_settings)

```makefile
# Shared make targets, included by each stack Makefile via the git repo root so
# they resolve whether the including Makefile is in stacks/<stack>/ or at root.

.PHONY: help
help: ## Print available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-22s\033[0m %s\n", $$1, $$2}'

.PHONY: cc
cc: ## Run Claude Code with useful config settings
	@caffeinate -di claude --enable-auto-mode --remote-control

.PHONY: apply_repo_settings
apply_repo_settings: ## Reconcile this repo's main ruleset + PR-merge prefs with .github/repo-settings/ (diff + confirm)
	@python3 $(REPO_ROOT)/scripts/apply_repo_settings.py
```

- [ ] **Step 2: Verify it parses (no stack Makefile yet — use a throwaway include)**

Run:
```bash
printf 'REPO_ROOT := $(shell git rev-parse --show-toplevel)\ninclude mk/shared.mk\n' > /tmp/_t.mk && make -f /tmp/_t.mk help && rm /tmp/_t.mk
```
Expected: prints the `help`, `cc`, `apply_repo_settings` lines with no make error.

- [ ] **Step 3: Commit**

```bash
git add mk/shared.mk
git commit -m "feat: mk/shared.mk — shared make targets (help, cc, apply_repo_settings)"
```

---

## Task 9: Python stack scaffold (`stacks/python/`)

**Files:**
- Create: `stacks/python/.python-version`
- Create: `stacks/python/pyproject.toml`
- Create: `stacks/python/Makefile`
- Create: `stacks/python/src/example_app/__init__.py`
- Create: `stacks/python/src/example_app/greeting.py`
- Create: `stacks/python/tests/test_greeting.py`
- Create: `stacks/python/README.md` (stack quickstart; becomes part of root README context post-init is handled separately — this is a short stack note)

- [ ] **Step 1: Create `stacks/python/.python-version`**

```
3.13.5
```

- [ ] **Step 2: Create `stacks/python/pyproject.toml`** (genericized from gridium-agent)

```toml
[project]
name = "{{PROJECT_NAME}}"
version = "0.1.0"
description = "{{DESCRIPTION}}"
readme = "README.md"
requires-python = "==3.13.5"
dependencies = [
    "pydantic>=2.12",
    "python-dotenv>=1.2",
]

[build-system]
requires = ["uv_build>=0.9.15,<0.12.0"]
build-backend = "uv_build"

[dependency-groups]
dev = [
    "bandit>=1.9.4",
    "black>=26.3.0",
    "mypy>=1.13.0",
    "pytest>=9.0.0",
    "pytest-cov>=7.1.0",
    "pytest-xdist>=3.6.1",
    "ruff>=0.14.0",
]

[tool.black]
line-length = 88

[tool.mypy]
python_version = "3.13"
plugins = ["pydantic.mypy"]
files = ["src", "tests"]
ignore_missing_imports = true
show_error_codes = true
disallow_untyped_defs = true

[tool.ruff]
line-length = 88
target-version = "py313"

[tool.ruff.lint]
extend-select = ["E501", "W", "D"]
extend-ignore = ["D107"]

[tool.ruff.lint.pydocstyle]
convention = "numpy"

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["E501", "D100", "D101", "D102", "D103", "D104"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
addopts = "-n auto -m 'not e2e and not integration'"
markers = [
    "integration: marks tests that call live external APIs",
    "e2e: marks tests that exercise the full pipeline against live services",
]
```

- [ ] **Step 3: Create `stacks/python/Makefile`** (target parity; includes shared via git root)

```makefile
REPO_ROOT := $(shell git rev-parse --show-toplevel)
include $(REPO_ROOT)/mk/shared.mk

.PHONY: deps
deps: ## Install runtime + dev dependencies
	@uv sync --dev

.PHONY: format
format: ## Auto-format with black
	@uv run black src/ tests/

.PHONY: lint
lint: ## black --check + ruff + mypy
	@uv run black --check src/ tests/
	@uv run ruff check src/ tests/
	@uv run mypy

.PHONY: tests
tests: ## Run pytest (excludes e2e/integration)
	@uv run pytest -v --tb=short

.PHONY: coverage
coverage: ## pytest with coverage + 80% gate
	@uv run pytest --cov=src --cov-report=term-missing --cov-report=xml --cov-fail-under=80

.PHONY: security
security: ## bandit SAST scan
	@uv run bandit -r src/

.PHONY: pr_check
pr_check: lint tests ## lint + tests for PR readiness
```

- [ ] **Step 4: Write the failing test** — `stacks/python/tests/test_greeting.py`

```python
from example_app.greeting import greet


def test_greet_returns_personalized_message():
    assert greet("Gridium") == "Hello, Gridium!"


def test_greet_rejects_empty_name():
    import pytest

    with pytest.raises(ValueError):
        greet("")
```

- [ ] **Step 5: Run it to verify it fails**

Run: `cd stacks/python && uv sync --dev && uv run pytest tests/test_greeting.py -v; cd -`
Expected: FAIL — `ModuleNotFoundError: No module named 'example_app'`

- [ ] **Step 6: Create the package + minimal implementation**

`stacks/python/src/example_app/__init__.py`:
```python
"""Example application package for the Python backend template."""
```

`stacks/python/src/example_app/greeting.py`:
```python
"""A tiny example module that proves the stack's tooling works end to end."""


def greet(name: str) -> str:
    """Return a personalized greeting.

    Parameters
    ----------
    name : str
        The name to greet. Must be non-empty.

    Returns
    -------
    str
        A greeting of the form ``"Hello, <name>!"``.

    Raises
    ------
    ValueError
        If ``name`` is empty.
    """
    if not name:
        raise ValueError("name must be non-empty")
    return f"Hello, {name}!"
```

- [ ] **Step 7: Create `stacks/python/README.md`**

```markdown
# {{PROJECT_NAME}}

{{DESCRIPTION}}

Python backend managed with `uv`. Run `make deps` then `make pr_check`.
```

- [ ] **Step 8: Run the full gate to verify GREEN**

Run: `make -C stacks/python pr_check`
Expected: black --check, ruff, mypy, and pytest all PASS.

- [ ] **Step 9: Verify coverage + security gates pass too**

Run: `make -C stacks/python coverage && make -C stacks/python security`
Expected: coverage ≥ 80% (the sample is fully covered), bandit reports no issues.

- [ ] **Step 10: Commit**

```bash
git add stacks/python
git commit -m "feat: runnable Python/uv stack scaffold with green quality gates"
```

---

## Task 10: React stack scaffold (`stacks/react/`)

**Files:**
- Create: `stacks/react/package.json`
- Create: `stacks/react/biome.json`
- Create: `stacks/react/tsconfig.json`
- Create: `stacks/react/vite.config.ts`
- Create: `stacks/react/vitest.config.ts`
- Create: `stacks/react/index.html`
- Create: `stacks/react/src/main.tsx`
- Create: `stacks/react/src/App.tsx`
- Create: `stacks/react/src/components/Button.tsx`
- Create: `stacks/react/src/components/Button.test.tsx`
- Create: `stacks/react/src/test-setup.ts`
- Create: `stacks/react/Makefile`
- Create: `stacks/react/README.md`

- [ ] **Step 1: Create `stacks/react/package.json`**

```json
{
  "name": "{{PROJECT_NAME}}",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "coverage": "vitest run --coverage",
    "typecheck": "tsc --noEmit",
    "lint": "biome check .",
    "format": "biome format --write ."
  },
  "dependencies": {
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {
    "@biomejs/biome": "^2.0.0",
    "@testing-library/jest-dom": "^6.6.0",
    "@testing-library/react": "^16.1.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@vitejs/plugin-react": "^4.3.0",
    "@vitest/coverage-v8": "^3.0.0",
    "jsdom": "^25.0.0",
    "typescript": "^5.7.0",
    "vite": "^6.0.0",
    "vitest": "^3.0.0"
  }
}
```

- [ ] **Step 2: Create `stacks/react/biome.json`** (snapmeter formatting parity)

```json
{
  "$schema": "https://biomejs.dev/schemas/2.0.0/schema.json",
  "formatter": { "enabled": true, "indentStyle": "space", "indentWidth": 2, "lineWidth": 80 },
  "javascript": {
    "formatter": {
      "quoteStyle": "single",
      "semicolons": "always",
      "trailingCommas": "all",
      "arrowParentheses": "always"
    }
  },
  "linter": { "enabled": true, "rules": { "recommended": true } }
}
```

- [ ] **Step 3: Create `stacks/react/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noEmit": true,
    "skipLibCheck": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src"]
}
```

- [ ] **Step 4: Create `stacks/react/vite.config.ts`**

```typescript
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
});
```

- [ ] **Step 5: Create `stacks/react/vitest.config.ts`**

```typescript
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    coverage: {
      provider: 'v8',
      thresholds: { lines: 80, functions: 80, branches: 80, statements: 80 },
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/main.tsx', 'src/**/*.test.{ts,tsx}', 'src/test-setup.ts'],
    },
  },
});
```

- [ ] **Step 6: Create `stacks/react/src/test-setup.ts`**

```typescript
import '@testing-library/jest-dom/vitest';
```

- [ ] **Step 7: Create `stacks/react/index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{{PROJECT_NAME}}</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 8: Write the failing test** — `stacks/react/src/components/Button.test.tsx`

```typescript
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import userEvent from '@testing-library/user-event';
import { Button } from './Button';

describe('Button', () => {
  it('renders its label', () => {
    render(<Button label='Click me' onClick={() => {}} />);
    expect(screen.getByRole('button', { name: 'Click me' })).toBeInTheDocument();
  });

  it('calls onClick when pressed', async () => {
    const onClick = vi.fn();
    render(<Button label='Go' onClick={onClick} />);
    await userEvent.click(screen.getByRole('button', { name: 'Go' }));
    expect(onClick).toHaveBeenCalledOnce();
  });
});
```

> Note: this test imports `@testing-library/user-event`. Add it to `devDependencies` in Step 1's `package.json` (`"@testing-library/user-event": "^14.5.0"`) — include it now.

- [ ] **Step 9: Install deps and run the test to verify it fails**

Run: `cd stacks/react && bun install && bunx vitest run src/components/Button.test.tsx; cd -`
Expected: FAIL — cannot resolve `./Button`.

- [ ] **Step 10: Create the component + app shell**

`stacks/react/src/components/Button.tsx`:
```typescript
interface ButtonProps {
  label: string;
  onClick: () => void;
}

export function Button({ label, onClick }: ButtonProps) {
  return (
    <button type='button' onClick={onClick}>
      {label}
    </button>
  );
}
```

`stacks/react/src/App.tsx`:
```typescript
import { Button } from './components/Button';

export function App() {
  return (
    <main>
      <h1>{'{{PROJECT_NAME}}'}</h1>
      <Button label='Say hello' onClick={() => alert('Hello, Gridium!')} />
    </main>
  );
}
```

`stacks/react/src/main.tsx`:
```typescript
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';

const root = document.getElementById('root');
if (!root) {
  throw new Error('Root element #root not found');
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

- [ ] **Step 11: Create `stacks/react/Makefile`** (target parity; includes shared via git root)

```makefile
REPO_ROOT := $(shell git rev-parse --show-toplevel)
include $(REPO_ROOT)/mk/shared.mk

.PHONY: deps
deps: ## Install dependencies with bun
	@bun install

.PHONY: format
format: ## Auto-format with Biome
	@bunx biome format --write .

.PHONY: lint
lint: ## Biome check (lint+format) + tsc type-check
	@bunx biome check .
	@bunx tsc --noEmit

.PHONY: tests
tests: ## Run Vitest
	@bunx vitest run

.PHONY: coverage
coverage: ## Vitest with v8 coverage + 80% gate
	@bunx vitest run --coverage

.PHONY: security
security: ## Dependency CVE audit
	@bun audit

.PHONY: pr_check
pr_check: lint tests ## lint + tests for PR readiness
```

- [ ] **Step 12: Create `stacks/react/README.md`**

```markdown
# {{PROJECT_NAME}}

{{DESCRIPTION}}

React + TypeScript (Vite) managed with `bun`. Run `make deps` then `make pr_check`.
```

- [ ] **Step 13: Format then run the full gate to verify GREEN**

Run: `make -C stacks/react format && make -C stacks/react pr_check`
Expected: Biome check + `tsc --noEmit` + Vitest all PASS.

- [ ] **Step 14: Verify coverage gate**

Run: `make -C stacks/react coverage`
Expected: coverage ≥ 80% across the included source.

- [ ] **Step 15: Commit**

```bash
git add stacks/react
git commit -m "feat: runnable React.ts/bun stack scaffold (Biome snapmeter formatting, Vitest) with green gates"
```

---

## Task 11: Root dispatcher Makefile (pre-init)

**Files:**
- Create: `Makefile`

- [ ] **Step 1: Create the root dispatcher `Makefile`** (delegates to both stacks + machinery; owns the `init` target; includes shared targets)

```makefile
REPO_ROOT := $(shell git rev-parse --show-toplevel)
include mk/shared.mk

.PHONY: deps
deps: ## Install tooling + both stacks' dependencies
	@uv sync --dev
	@$(MAKE) -C stacks/python deps
	@$(MAKE) -C stacks/react deps

.PHONY: format
format: ## Format machinery + both stacks
	@uv run black scripts/ tests/
	@$(MAKE) -C stacks/python format
	@$(MAKE) -C stacks/react format

.PHONY: lint
lint: ## Lint machinery + both stacks
	@uv run black --check scripts/ tests/
	@uv run ruff check scripts/ tests/
	@uv run mypy
	@$(MAKE) -C stacks/python lint
	@$(MAKE) -C stacks/react lint

.PHONY: tests
tests: ## Machinery tests + both stacks' tests
	@uv run pytest tests/template -v --tb=short
	@$(MAKE) -C stacks/python tests
	@$(MAKE) -C stacks/react tests

.PHONY: pr_check
pr_check: lint tests ## lint + tests across machinery and both stacks

.PHONY: init
init: ## Initialize this template into a single-stack project. Usage: make init STACK=python|react PROJECT_NAME="name" DESCRIPTION="desc"
	@uv run python scripts/init_template.py --stack "$(STACK)" --project-name "$(PROJECT_NAME)" --description "$(DESCRIPTION)"
```

- [ ] **Step 2: Verify `make help` lists targets without error**

Run: `make help`
Expected: prints `deps`, `format`, `lint`, `tests`, `pr_check`, `init`, plus shared `cc`/`apply_repo_settings`. (`make tests`/`lint` will fail until Tasks 15–16 add `tests/template` + scripts; that's expected — only `help` must work here.)

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "feat: root dispatcher Makefile (delegates to both stacks + owns init target)"
```

---

## Task 12: GitHub CI, dependabot, PR template

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `.github/dependabot.yml`
- Create: `.github/PULL_REQUEST_TEMPLATE.md` (ported from gridium-agent)

- [ ] **Step 1: Create `.github/workflows/ci.yml`** (three pre-init jobs, marker-wrapped per stack; `template` job runs the machinery tests)

```yaml
name: ci

on:
  push:
    branches: [main]
  pull_request:

jobs:
# >>> STACK:python
  python:
    name: python (lint + tests + security)
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: stacks/python
    steps:
      - uses: actions/checkout@v6
      - name: Read Python version
        id: pyver
        run: echo "value=$(cat .python-version)" >> "$GITHUB_OUTPUT"
      - uses: actions/setup-python@v6
        with:
          python-version: ${{ steps.pyver.outputs.value }}
      - uses: astral-sh/setup-uv@v7
      - run: make deps
      - run: make lint
      - run: make coverage
      - run: make security
# <<< STACK:python
# >>> STACK:react
  react:
    name: react (lint + tests + security)
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: stacks/react
    steps:
      - uses: actions/checkout@v6
      - uses: oven-sh/setup-bun@v2
      - run: make deps
      - run: make lint
      - run: make coverage
      - run: make security
# <<< STACK:react
# >>> STACK:template
  template:
    name: template machinery tests
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: "3.13.5"
      - uses: astral-sh/setup-uv@v7
      - run: uv sync --dev
      - run: uv run pytest tests/template -v
# <<< STACK:template
```

- [ ] **Step 2: Create `.github/dependabot.yml`** (marker-wrapped per ecosystem)

```yaml
version: 2
updates:
# >>> STACK:python
  - package-ecosystem: "pip"
    directory: "/stacks/python"
    schedule:
      interval: "weekly"
    labels: ["dependencies", "python"]
    commit-message:
      prefix: "deps"
# <<< STACK:python
# >>> STACK:react
  - package-ecosystem: "npm"
    directory: "/stacks/react"
    schedule:
      interval: "weekly"
    labels: ["dependencies", "javascript"]
    commit-message:
      prefix: "deps"
# <<< STACK:react
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
    labels: ["dependencies", "github-actions"]
    commit-message:
      prefix: "ci"
```

> Note: at init, the `directory:` for the kept stack changes from `/stacks/<stack>` to `/` (the stack is promoted to root). `init_template.py` handles this rewrite (Task 16, Step on dependabot).

- [ ] **Step 3: Port the PR template**

```bash
G=~/Documents/Projects/gridium-agent
git -C "$G" show "origin/main:.github/PULL_REQUEST_TEMPLATE.md" > .github/PULL_REQUEST_TEMPLATE.md
```

- [ ] **Step 4: Validate the YAML parses**

Run: `python3 -c "import yaml,sys; [yaml.safe_load(open(f)) for f in ['.github/workflows/ci.yml','.github/dependabot.yml']]; print('valid')"`
Expected: `valid` (if PyYAML missing, `uv run --with pyyaml python3 -c …`).

- [ ] **Step 5: Verify stack markers balanced in both YAML files**

Run:
```bash
for s in python react; do
  for f in .github/workflows/ci.yml .github/dependabot.yml; do
    o=$(grep -c "# >>> STACK:$s" "$f"); c=$(grep -c "# <<< STACK:$s" "$f")
    [ "$o" = "$c" ] && echo "$f $s ok" || echo "$f $s UNBALANCED"
  done
done
```
Expected: all `ok`.

- [ ] **Step 6: Commit**

```bash
git add .github
git commit -m "feat: dual-stack CI (python/react/template jobs) + dependabot + PR template"
```

---

## Task 13: Canonical repo-settings artifact (`.github/repo-settings/`)

**Files:**
- Create: `.github/repo-settings/ruleset.json`
- Create: `.github/repo-settings/merge-settings.json`

- [ ] **Step 1: Create `.github/repo-settings/ruleset.json`** (sanitized canonical `main` ruleset)

```json
{
  "name": "main",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": { "include": ["refs/heads/main"], "exclude": [] }
  },
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": true,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": true,
        "required_reviewers": [],
        "allowed_merge_methods": ["squash"]
      }
    },
    {
      "type": "copilot_code_review",
      "parameters": { "review_on_push": false, "review_draft_pull_requests": false }
    }
  ],
  "bypass_actors": []
}
```

- [ ] **Step 2: Create `.github/repo-settings/merge-settings.json`**

```json
{
  "allow_squash_merge": true,
  "allow_merge_commit": false,
  "allow_rebase_merge": false,
  "allow_auto_merge": true,
  "delete_branch_on_merge": true,
  "squash_merge_commit_title": "COMMIT_OR_PR_TITLE",
  "squash_merge_commit_message": "COMMIT_MESSAGES"
}
```

- [ ] **Step 3: Validate JSON**

Run: `python3 -c "import json; [json.load(open(f)) for f in ['.github/repo-settings/ruleset.json','.github/repo-settings/merge-settings.json']]; print('valid')"`
Expected: `valid`

- [ ] **Step 4: Commit**

```bash
git add .github/repo-settings
git commit -m "feat: canonical .github/repo-settings (main ruleset + PR-merge prefs)"
```

---

## Task 14: `apply_repo_settings.py` + tests (TDD)

**Files:**
- Create: `scripts/apply_repo_settings.py`
- Test: `tests/template/test_apply_repo_settings.py`

- [ ] **Step 1: Write the failing test** — `tests/template/test_apply_repo_settings.py`

```python
import json
from pathlib import Path

from scripts.apply_repo_settings import (
    find_main_ruleset,
    ruleset_matches,
    merge_settings_match,
    plan_actions,
    load_desired,
)

REPO_SETTINGS = Path(__file__).resolve().parents[2] / ".github" / "repo-settings"


def test_load_desired_reads_both_files():
    desired = load_desired(REPO_SETTINGS)
    assert desired.ruleset["name"] == "main"
    assert desired.merge["allow_squash_merge"] is True


def test_find_main_ruleset_returns_match():
    existing = [{"id": 1, "name": "other"}, {"id": 2, "name": "main"}]
    assert find_main_ruleset(existing)["id"] == 2


def test_find_main_ruleset_none_when_absent():
    assert find_main_ruleset([{"id": 1, "name": "develop"}]) is None


def test_ruleset_matches_true_when_rules_equal():
    desired = {"name": "main", "enforcement": "active",
               "rules": [{"type": "deletion"}]}
    current = {"name": "main", "enforcement": "active",
               "rules": [{"type": "deletion"}], "id": 99, "created_at": "x"}
    assert ruleset_matches(desired, current) is True


def test_ruleset_matches_false_when_rules_differ():
    desired = {"name": "main", "enforcement": "active", "rules": [{"type": "deletion"}]}
    current = {"name": "main", "enforcement": "active", "rules": []}
    assert ruleset_matches(desired, current) is False


def test_merge_settings_match_ignores_extra_current_keys():
    desired = {"allow_squash_merge": True, "allow_merge_commit": False}
    current = {"allow_squash_merge": True, "allow_merge_commit": False, "extra": 1}
    assert merge_settings_match(desired, current) is True


def test_plan_actions_post_when_no_ruleset():
    desired_rs = {"name": "main", "enforcement": "active", "rules": []}
    desired_merge = {"allow_squash_merge": True}
    actions = plan_actions(
        current_rulesets=[],
        current_merge={"allow_squash_merge": False},
        desired_ruleset=desired_rs,
        desired_merge=desired_merge,
    )
    assert ("ruleset", "POST", None) in actions
    assert any(a[0] == "merge" and a[1] == "PATCH" for a in actions)


def test_plan_actions_put_when_main_exists_and_differs():
    desired_rs = {"name": "main", "enforcement": "active", "rules": [{"type": "deletion"}]}
    actions = plan_actions(
        current_rulesets=[{"id": 7, "name": "main", "enforcement": "active", "rules": []}],
        current_merge={"allow_squash_merge": True},
        desired_ruleset=desired_rs,
        desired_merge={"allow_squash_merge": True},
    )
    assert ("ruleset", "PUT", 7) in actions
    assert all(a[0] != "merge" for a in actions)  # merge already aligned → no-op


def test_plan_actions_all_noop_when_aligned():
    desired_rs = {"name": "main", "enforcement": "active", "rules": [{"type": "deletion"}]}
    actions = plan_actions(
        current_rulesets=[{"id": 7, "name": "main", "enforcement": "active", "rules": [{"type": "deletion"}]}],
        current_merge={"allow_squash_merge": True},
        desired_ruleset=desired_rs,
        desired_merge={"allow_squash_merge": True},
    )
    assert actions == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/template/test_apply_repo_settings.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.apply_repo_settings'`

- [ ] **Step 3: Create `scripts/__init__.py`** (so `scripts.apply_repo_settings` imports in tests)

```python
```
(empty file)

- [ ] **Step 4: Implement `scripts/apply_repo_settings.py`**

```python
#!/usr/bin/env python3
"""Reconcile this repo's `main` ruleset + PR-merge prefs with .github/repo-settings/.

Reads the canonical settings, diffs them against the live repo (via `gh`), prints
the diff, and — unless ``--yes`` — asks for confirmation before applying. Idempotent.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_SETTINGS_DIR = Path(__file__).resolve().parent.parent / ".github" / "repo-settings"

# Ruleset fields we assert; everything else (id, timestamps, _links) is ignored.
_RULESET_KEYS = ("name", "target", "enforcement", "conditions", "rules", "bypass_actors")


@dataclass
class Desired:
    """The canonical settings loaded from disk."""

    ruleset: dict
    merge: dict


def load_desired(settings_dir: Path) -> Desired:
    """Load the desired ruleset + merge settings from ``settings_dir``."""
    ruleset = json.loads((settings_dir / "ruleset.json").read_text(encoding="utf-8"))
    merge = json.loads((settings_dir / "merge-settings.json").read_text(encoding="utf-8"))
    return Desired(ruleset=ruleset, merge=merge)


def find_main_ruleset(existing: list[dict]) -> dict | None:
    """Return the ruleset named ``main`` from ``existing``, or None."""
    for rs in existing:
        if rs.get("name") == "main":
            return rs
    return None


def ruleset_matches(desired: dict, current: dict) -> bool:
    """True when ``current`` already matches ``desired`` on the asserted keys."""
    return all(desired.get(k) == current.get(k) for k in _RULESET_KEYS if k in desired)


def merge_settings_match(desired: dict, current: dict) -> bool:
    """True when every desired merge key already has the desired value."""
    return all(current.get(k) == v for k, v in desired.items())


def plan_actions(
    current_rulesets: list[dict],
    current_merge: dict,
    desired_ruleset: dict,
    desired_merge: dict,
) -> list[tuple]:
    """Compute the minimal set of apply actions.

    Returns a list of tuples: ``("ruleset", "POST"|"PUT", id_or_None)`` and/or
    ``("merge", "PATCH", None)``. Empty list means everything is already aligned.
    """
    actions: list[tuple] = []
    main = find_main_ruleset(current_rulesets)
    if main is None:
        actions.append(("ruleset", "POST", None))
    elif not ruleset_matches(desired_ruleset, main):
        actions.append(("ruleset", "PUT", main["id"]))
    if not merge_settings_match(desired_merge, current_merge):
        actions.append(("merge", "PATCH", None))
    return actions


def _gh_json(args: list[str], runner=subprocess.run) -> object:
    """Run a `gh` command and parse its stdout as JSON."""
    proc = runner(["gh", *args], capture_output=True, text=True, check=True)
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def _current_repo(runner=subprocess.run) -> str:
    proc = runner(
        ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
        capture_output=True, text=True, check=True,
    )
    return proc.stdout.strip()


def main(argv: list[str] | None = None, runner=subprocess.run) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="apply without confirmation")
    parser.add_argument("--settings-dir", default=str(REPO_SETTINGS_DIR))
    args = parser.parse_args(argv)

    desired = load_desired(Path(args.settings_dir))
    repo = _current_repo(runner)
    current_rulesets = _gh_json(["api", f"repos/{repo}/rulesets"], runner) or []
    current_merge = _gh_json(["api", f"repos/{repo}"], runner) or {}

    actions = plan_actions(current_rulesets, current_merge, desired.ruleset, desired.merge)
    if not actions:
        print(f"{repo}: settings already aligned — no changes.")
        return 0

    print(f"{repo}: planned changes:")
    for kind, method, ident in actions:
        print(f"  - {kind}: {method}" + (f" (id={ident})" if ident else ""))

    if not args.yes:
        reply = input("Apply these changes? [y/N] ").strip().lower()
        if reply != "y":
            print("Aborted.")
            return 1

    for kind, method, ident in actions:
        if kind == "ruleset" and method == "POST":
            runner(["gh", "api", "--method", "POST", f"repos/{repo}/rulesets",
                    "--input", "-"], input=json.dumps(desired.ruleset), text=True, check=True)
        elif kind == "ruleset" and method == "PUT":
            runner(["gh", "api", "--method", "PUT", f"repos/{repo}/rulesets/{ident}",
                    "--input", "-"], input=json.dumps(desired.ruleset), text=True, check=True)
        elif kind == "merge":
            merge_args = ["gh", "api", "--method", "PATCH", f"repos/{repo}"]
            for k, v in desired.merge.items():
                merge_args += ["-f", f"{k}={json.dumps(v) if not isinstance(v, str) else v}"]
            runner(merge_args, check=True)
    print("Applied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run tests to verify GREEN**

Run: `uv run pytest tests/template/test_apply_repo_settings.py -v`
Expected: all 9 tests PASS.

- [ ] **Step 6: Lint the script**

Run: `uv run black scripts/ tests/ && uv run ruff check scripts/ && uv run mypy`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add scripts/apply_repo_settings.py scripts/__init__.py tests/template/test_apply_repo_settings.py
git commit -m "feat: apply_repo_settings.py with diff/PUT/POST/no-op logic (TDD)"
```

---

## Task 15: `init_template.py` text-transform helpers + tests (TDD)

**Files:**
- Create: `scripts/init_template.py` (helpers first; `initialize()` added in Task 16)
- Test: `tests/template/test_init_helpers.py`

- [ ] **Step 1: Write the failing test** — `tests/template/test_init_helpers.py`

```python
from scripts.init_template import (
    filter_html_markers,
    filter_yaml_markers,
    strip_interview,
    fill_placeholders,
)


def test_filter_html_keeps_chosen_unwraps_markers():
    text = (
        "A\n<!-- STACK:python -->\nPY\n<!-- /STACK:python -->\n"
        "<!-- STACK:react -->\nRE\n<!-- /STACK:react -->\nB\n"
    )
    out = filter_html_markers(text, "python")
    assert "PY" in out
    assert "RE" not in out
    assert "STACK:python" not in out
    assert "STACK:react" not in out


def test_filter_html_react_drops_python():
    text = "<!-- STACK:python -->\nPY\n<!-- /STACK:python -->\n<!-- STACK:react -->\nRE\n<!-- /STACK:react -->\n"
    out = filter_html_markers(text, "react")
    assert "RE" in out and "PY" not in out


def test_filter_yaml_keeps_chosen():
    text = (
        "jobs:\n# >>> STACK:python\n  py: 1\n# <<< STACK:python\n"
        "# >>> STACK:react\n  re: 2\n# <<< STACK:react\n"
        "# >>> STACK:template\n  tmpl: 3\n# <<< STACK:template\n"
    )
    out = filter_yaml_markers(text, "python")
    assert "py: 1" in out
    assert "re: 2" not in out
    assert "tmpl: 3" not in out  # the template job is dropped post-init
    assert "STACK:" not in out


def test_strip_interview_removes_block():
    text = "intro\n<!-- INTERVIEW:start -->\nPROMPT\n<!-- INTERVIEW:end -->\noutro\n"
    out = strip_interview(text)
    assert "PROMPT" not in out
    assert "intro" in out and "outro" in out


def test_fill_placeholders():
    text = "name={{PROJECT_NAME}} desc={{DESCRIPTION}}"
    assert fill_placeholders(text, "acme", "a thing") == "name=acme desc=a thing"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/template/test_init_helpers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.init_template'`

- [ ] **Step 3: Implement the helpers in `scripts/init_template.py`**

```python
#!/usr/bin/env python3
"""Initialize this dual-stack template into a single-stack project.

`make init STACK=python|react ...` promotes the chosen stack's files to the repo
root, prunes the other stack, rewrites the marker-wrapped generated files, applies
the repo settings, and deletes the template-only machinery.
"""

from __future__ import annotations

import re

STACKS = ("python", "react")


def _other(stack: str) -> str:
    return "react" if stack == "python" else "python"


def filter_html_markers(text: str, keep: str) -> str:
    """Drop the non-kept stack's HTML-marker blocks; unwrap the kept stack's markers."""
    other = _other(keep)
    text = re.sub(
        rf"<!-- STACK:{other} -->.*?<!-- /STACK:{other} -->\n?", "", text, flags=re.S
    )
    text = re.sub(rf"<!-- /?STACK:{keep} -->\n?", "", text)
    return text


def filter_yaml_markers(text: str, keep: str) -> str:
    """Drop every YAML-marker block except the kept stack's; unwrap the kept markers.

    The ``template`` block is always dropped (machinery is removed post-init).
    """
    for name in ("python", "react", "template"):
        if name == keep:
            continue
        text = re.sub(
            rf"^[ \t]*# >>> STACK:{name}\b.*?^[ \t]*# <<< STACK:{name}\b.*?\n",
            "",
            text,
            flags=re.S | re.M,
        )
    text = re.sub(rf"^[ \t]*# (?:>>>|<<<) STACK:{keep}\b.*?\n", "", text, flags=re.M)
    return text


def strip_interview(text: str) -> str:
    """Remove the README interview prompt block."""
    return re.sub(
        r"<!-- INTERVIEW:start -->.*?<!-- INTERVIEW:end -->\n?", "", text, flags=re.S
    )


def fill_placeholders(text: str, project_name: str, description: str) -> str:
    """Replace ``{{PROJECT_NAME}}`` and ``{{DESCRIPTION}}`` tokens."""
    return text.replace("{{PROJECT_NAME}}", project_name).replace(
        "{{DESCRIPTION}}", description
    )
```

- [ ] **Step 4: Run tests to verify GREEN**

Run: `uv run pytest tests/template/test_init_helpers.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/init_template.py tests/template/test_init_helpers.py
git commit -m "feat: init_template marker/placeholder text-transform helpers (TDD)"
```

---

## Task 16: `init_template.py` `initialize()` transform + tests (TDD)

**Files:**
- Modify: `scripts/init_template.py` (add `initialize()` + CLI)
- Test: `tests/template/test_initialize.py`
- Create: `tests/template/conftest.py` (fixture that copies the live tree into tmp)

- [ ] **Step 1: Create `tests/template/conftest.py`**

```python
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def template_tree(tmp_path: Path) -> Path:
    """A throwaway copy of the template repo (no .git, no .venv, no node_modules)."""
    dest = tmp_path / "repo"
    shutil.copytree(
        REPO_ROOT,
        dest,
        ignore=shutil.ignore_patterns(
            ".git", ".venv", "node_modules", "__pycache__", "*.pyc", "dist", "htmlcov"
        ),
    )
    return dest
```

- [ ] **Step 2: Write the failing test** — `tests/template/test_initialize.py`

```python
import pytest

from scripts.init_template import initialize


def test_initialize_python_promotes_and_prunes(template_tree):
    initialize(template_tree, "python", "acme-svc", "A backend service",
               apply_settings=False)
    assert not (template_tree / "stacks").exists()
    assert (template_tree / "pyproject.toml").exists()
    assert (template_tree / "src" / "example_app" / "greeting.py").exists()
    assert (template_tree / "Makefile").exists()
    # other stack's rules gone, chosen + shared kept
    assert not (template_tree / ".agents" / "rules" / "react").exists()
    assert (template_tree / ".agents" / "rules" / "python").exists()
    assert (template_tree / ".agents" / "rules" / "shared").exists()
    # machinery self-destructed
    assert not (template_tree / "scripts" / "init_template.py").exists()
    assert not (template_tree / "tests" / "template").exists()
    # AGENTS.md collapsed + filled
    agents = (template_tree / "AGENTS.md").read_text()
    assert "acme-svc" in agents
    assert "STACK:react" not in agents and "STACK:python" not in agents
    assert "bun-react" not in agents
    # ci.yml single-stack
    ci = (template_tree / ".github" / "workflows" / "ci.yml").read_text()
    assert "react" not in ci and "template machinery" not in ci
    assert "STACK:" not in ci
    # README interview stripped
    readme = (template_tree / "README.md").read_text()
    assert "INTERVIEW:start" not in readme
    # apply_repo_settings kept
    assert (template_tree / "scripts" / "apply_repo_settings.py").exists()
    assert (template_tree / ".github" / "repo-settings" / "ruleset.json").exists()


def test_initialize_react_removes_root_python_tooling(template_tree):
    initialize(template_tree, "react", "acme-web", "A frontend app",
               apply_settings=False)
    assert not (template_tree / "stacks").exists()
    assert (template_tree / "package.json").exists()
    assert (template_tree / "biome.json").exists()
    # root template-tooling pyproject removed (react brought none)
    assert not (template_tree / "pyproject.toml").exists()
    assert not (template_tree / ".agents" / "rules" / "python").exists()
    pkg = (template_tree / "package.json").read_text()
    assert "acme-web" in pkg


def test_initialize_rejects_bad_stack(template_tree):
    with pytest.raises(ValueError):
        initialize(template_tree, "rust", "x", "y", apply_settings=False)


def test_initialize_refuses_when_already_initialized(template_tree):
    initialize(template_tree, "python", "acme", "svc", apply_settings=False)
    with pytest.raises(RuntimeError):
        initialize(template_tree, "python", "acme", "svc", apply_settings=False)
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/template/test_initialize.py -v`
Expected: FAIL — `ImportError: cannot import name 'initialize'`

- [ ] **Step 4: Append `initialize()` + CLI to `scripts/init_template.py`**

```python
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# Files rewritten at init: (relative path, marker kind). "html" → filter_html_markers,
# "yaml" → filter_yaml_markers, "fill" → placeholders only.
_HTML_FILES = ("AGENTS.md", "README.md")
_YAML_FILES = (".github/workflows/ci.yml", ".github/dependabot.yml")
_FILL_ONLY = ("pyproject.toml", "package.json", "index.html",
              "src/App.tsx", "README.md")


def _promote(root: Path, stack: str) -> None:
    """Move stacks/<stack>/* up to the repo root, replacing colliding entries."""
    chosen = root / "stacks" / stack
    for item in chosen.iterdir():
        dest = root / item.name
        if dest.is_dir():
            shutil.rmtree(dest)
        elif dest.exists():
            dest.unlink()
        shutil.move(str(item), str(dest))


def _rewrite_dependabot_dir(root: Path, stack: str) -> None:
    """After promotion the kept stack lives at root → point dependabot at '/'."""
    path = root / ".github" / "dependabot.yml"
    if path.exists():
        text = path.read_text(encoding="utf-8").replace(f"/stacks/{stack}", "/")
        path.write_text(text, encoding="utf-8")


def initialize(
    root,
    stack: str,
    project_name: str,
    description: str,
    apply_settings: bool = False,
    runner=subprocess.run,
) -> None:
    """Collapse the template into a single-stack project rooted at ``root``."""
    root = Path(root)
    if stack not in STACKS:
        raise ValueError(f"stack must be one of {STACKS}, got {stack!r}")
    if not (root / "stacks").is_dir():
        raise RuntimeError("no stacks/ directory — repo already initialized?")
    if not (root / "stacks" / stack).is_dir():
        raise RuntimeError(f"stacks/{stack} not found")

    # 2. Promote chosen stack to root, then 3. prune.
    _promote(root, stack)
    shutil.rmtree(root / "stacks")
    other_rules = root / ".agents" / "rules" / _other(stack)
    if other_rules.is_dir():
        shutil.rmtree(other_rules)

    # 4. Rewrite generated files.
    for rel in _HTML_FILES:
        p = root / rel
        if p.exists():
            p.write_text(filter_html_markers(p.read_text(encoding="utf-8"), stack),
                         encoding="utf-8")
    for rel in _YAML_FILES:
        p = root / rel
        if p.exists():
            p.write_text(filter_yaml_markers(p.read_text(encoding="utf-8"), stack),
                         encoding="utf-8")
    readme = root / "README.md"
    if readme.exists():
        readme.write_text(strip_interview(readme.read_text(encoding="utf-8")),
                          encoding="utf-8")
    _rewrite_dependabot_dir(root, stack)
    for rel in _FILL_ONLY:
        p = root / rel
        if p.exists():
            p.write_text(fill_placeholders(p.read_text(encoding="utf-8"),
                                           project_name, description), encoding="utf-8")

    # 6. Self-destruct machinery (5. apply settings handled by CLI, below).
    to_remove = [root / "scripts" / "init_template.py", root / "tests" / "template"]
    if stack == "react":
        to_remove += [root / "pyproject.toml", root / "uv.lock",
                      root / ".python-version", root / "scripts" / "__init__.py"]
    for p in to_remove:
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
    tests_dir = root / "tests"
    if tests_dir.is_dir() and not any(tests_dir.iterdir()):
        tests_dir.rmdir()

    if apply_settings:
        runner([sys.executable, str(root / "scripts" / "apply_repo_settings.py")],
               check=True)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for `make init`."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack", required=True, choices=STACKS)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--skip-settings", action="store_true")
    args = parser.parse_args(argv)
    initialize(
        Path.cwd(),
        args.stack,
        args.project_name,
        args.description,
        apply_settings=not args.skip_settings,
    )
    print(f"Initialized as a {args.stack} project. Review the tree, then commit and push.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

> Note: the `import` block at the top of this appended section duplicates `re` already imported in Task 15. Consolidate all imports at the top of the file (`from __future__ import annotations`, then `argparse`, `re`, `shutil`, `subprocess`, `sys`, `from pathlib import Path`) — do not leave a second import block mid-file.

- [ ] **Step 5: Run the initialize tests to verify GREEN**

Run: `uv run pytest tests/template/test_initialize.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 6: Run the full machinery suite + lint**

Run: `uv run pytest tests/template -v && uv run black --check scripts/ tests/ && uv run ruff check scripts/ tests/ && uv run mypy`
Expected: all PASS, no lint/type errors.

- [ ] **Step 7: Commit**

```bash
git add scripts/init_template.py tests/template/test_initialize.py tests/template/conftest.py
git commit -m "feat: init_template initialize() promote/prune/rewrite/self-destruct (TDD)"
```

---

## Task 17: README with the required interview prompt

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace `README.md`** with the template overview + the marker-wrapped interview prompt

````markdown
# agentic-ai-powered-repo

A Gridium template repo that seeds new repos with our AI-powered development best
practices — CI/CD, testing, agent rules/skills, and repo settings — for either a
Python backend or a React + TypeScript frontend.

<!-- INTERVIEW:start -->
## Start here: initialize this template

Paste the prompt below into your agentic coding harness (Claude Code, Cursor, …).
It interviews you about the repo you're building, then runs `make init` and
reconciles this repo's `main` branch protection + PR-merge settings.

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
- `make init STACK=<python|react> PROJECT_NAME="<name>" DESCRIPTION="<desc>"`
  (this promotes the chosen stack to root, prunes the other, and removes the
  template machinery).
- `make apply_repo_settings` (it prints a diff of this repo's main ruleset +
  PR-merge prefs vs the canonical settings and asks you to confirm before
  applying).
- Stage everything and make the initial commit:
  `git add -A && git commit -m "chore: initialize from agentic-ai-powered-repo template"`.
- Tell the user to push, and run `make deps && make pr_check` to confirm the
  stack is green.

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

See `docs/superpowers/specs/2026-06-09-cicd-testing-template-design.md` for the design.
````

- [ ] **Step 2: Verify interview + stack markers are present and balanced**

Run:
```bash
grep -c 'INTERVIEW:start' README.md; grep -c 'INTERVIEW:end' README.md
```
Expected: `1` and `1`.

- [ ] **Step 3: Sanity-check `init`'s README transform in a temp copy**

Run:
```bash
uv run python -c "
from pathlib import Path; import tempfile, shutil
from scripts.init_template import strip_interview
t = strip_interview(Path('README.md').read_text())
assert 'INTERVIEW' not in t and 'What this template provides' in t
print('interview strips cleanly')
"
```
Expected: `interview strips cleanly`

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: README with required harness-agnostic interview prompt"
```

---

## Task 18: Whole-template verification pass

**Files:** none (verification only)

- [ ] **Step 1: Install everything**

Run: `make deps`
Expected: tooling + both stacks install with no error.

- [ ] **Step 2: Run the full pre-init gate**

Run: `make pr_check`
Expected: machinery lint+tests, python `pr_check`, and react `pr_check` all PASS.

- [ ] **Step 3: Verify both stacks' coverage + security gates**

Run: `make -C stacks/python coverage && make -C stacks/python security && make -C stacks/react coverage && make -C stacks/react security`
Expected: all PASS (≥80% coverage each; no security findings).

- [ ] **Step 4: Dry-run the real init in a throwaway git clone (python), then react**

Run:
```bash
tmp=$(mktemp -d); git clone -q . "$tmp/py"; ( cd "$tmp/py" && make init STACK=python PROJECT_NAME="probe-svc" DESCRIPTION="probe" --skip-settings 2>/dev/null || uv run python scripts/init_template.py --stack python --project-name probe-svc --description probe --skip-settings ) && ( cd "$tmp/py" && make deps && make pr_check ) && echo "PYTHON INIT E2E GREEN"
git clone -q . "$tmp/re"; ( cd "$tmp/re" && uv run python scripts/init_template.py --stack react --project-name probe-web --description probe --skip-settings ) && ( cd "$tmp/re" && make deps && make pr_check ) && echo "REACT INIT E2E GREEN"
rm -rf "$tmp"
```
Expected: `PYTHON INIT E2E GREEN` and `REACT INIT E2E GREEN`. (This is the dry run; the orchestrator's Step 6 E2E re-runs this as the source of truth.)

- [ ] **Step 5: Confirm no stale gridium-agent / agentrules references leaked**

Run: `grep -rn 'gridium_agent\|agentrules\|langfuse\|AZURE_FOUNDRY' --include='*.md' --include='*.toml' --include='*.json' --include='Makefile' . | grep -v docs/superpowers || echo "clean"`
Expected: `clean`

- [ ] **Step 6: Commit any fixes surfaced**

```bash
git add -A && git commit -m "chore: whole-template verification fixes" || echo "nothing to fix"
```

---

## Self-Review (completed by plan author)

**1. Spec coverage:**
- Shared agent infra (AGENTS.md router, CLAUDE.md, .cursor, .mcp.json, rules shared/python/react, skills + single symlink, hooks, settings) → Tasks 2–8. ✓
- Both runnable stacks + Makefile parity + mk/shared.mk → Tasks 8–11. ✓
- Dual-job CI + dependabot + PR template; .circleci dropped (none exists in this repo, so nothing to delete) → Task 12. ✓
- `.github/repo-settings/` artifact → Task 13. ✓
- `apply_repo_settings.py` (stdlib) → Task 14. ✓
- `init_template.py` (pure helpers + `initialize()`) → Tasks 15–16. ✓
- README interview prompt (prefers native structured-interview tooling) → Task 17. ✓
- Testing strategy (machinery tests + each stack's sample tests + E2E dry-run) → Tasks 9, 10, 14, 15, 16, 18. ✓

**2. Placeholder scan:** No "TBD/TODO/implement later". `{{PROJECT_NAME}}`/`{{DESCRIPTION}}` and `src/<your_package>` are intentional template tokens, not plan placeholders. ✓

**3. Type consistency:** `initialize(root, stack, project_name, description, apply_settings, runner)` and helpers `filter_html_markers`/`filter_yaml_markers`/`strip_interview`/`fill_placeholders` are referenced identically in Tasks 15–18. `plan_actions`/`ruleset_matches`/`merge_settings_match`/`find_main_ruleset`/`load_desired` match between Task 14's code and tests. Makefile verbs (`deps/format/lint/tests/coverage/security/pr_check`) are identical across both stack Makefiles and the dispatcher. ✓
