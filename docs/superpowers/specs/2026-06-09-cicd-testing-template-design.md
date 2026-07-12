# Align repo with CI/CD + testing best practices — dual-stack template design

**Issue:** [#1 — Align repo with CI/CD and testing best practices we have in gridium-agent](https://github.com/Gridium/agentic-ai-powered-repo/issues/1)
**Date:** 2026-06-09
**Status:** Approved (brainstorming) → ready for implementation plan

## Problem

`agentic-ai-powered-repo` is a GitHub **template repo**: its job is to seed *new*
repos with Gridium's AI-powered development best practices. Today it is a partial
copy-paste of `gridium-agent` — the `Makefile` references `src/gridium_agent`,
Azure Foundry, langfuse, and `conf/llms.yaml`, none of which exist here. So it is
neither a clean template nor a runnable repo.

This work turns it into a real template that:

1. Carries **both** a Python/`uv` backend stack and a Vite + React + TypeScript/`bun`
   frontend stack, each runnable (build/lint/test green) out of the box.
2. Makes the active package manager unambiguous and aligns rules/skills/config to
   whether the spawned repo is frontend or backend.
3. Captures dev skills harness-agnostically under `.agents/skills/` and shared rules
   under `.agents/rules/`, routed via `AGENTS.md`.
4. Makes the `Makefile` the single orchestrator of CI checks and of driving Claude
   Code (`make cc`).
5. Ships a **required** README interview prompt that any agentic harness can run to
   interview the new-repo owner (frontend vs backend, language/framework prefs seeded
   with Gridium org defaults) and that reconciles the new repo's `main`
   branch-protection ruleset + PR-merge preferences with the template's canonical
   settings.

**Reference:** `gridium-agent` `origin/main` only (for backend best practices) and
`Gridium/snapmeter` `main` (for frontend formatting alignment). The frontend stack
is otherwise a *new* in-house convention — gridium-agent is backend-only and
snapmeter is a legacy Ember monorepo being jettisoned in favor of React.ts.

## Strategy: carry both, prune at init

The template carries both stacks in isolated subdirectories. A `make init` step
(driven by the interview agent) promotes the chosen stack to the repo root, prunes
the other, rewrites the generated files to the single chosen stack, applies the repo
settings, and deletes the template-only machinery. The result is a clean,
single-stack repo.

Chosen over: *interview-first / scaffold-on-demand* (stacks wouldn't be runnable or
CI-proven pre-init) and *backend-now / frontend-stub* (issue wants both stacks
real now).

## Architecture: stack-isolated subdirectories + `make init` promotion

Selected over *coexist-at-root* (toolchain/config collisions: two lockfiles, ruff vs
biome both globbing root, AGENTS.md/CI straddling both messily) and
*generate-on-init* (stacks not runnable/CI-proven pre-init).

### Pre-init layout

```
/
├── AGENTS.md                      # single source of truth; routes to .agents/rules; describes BOTH stacks
├── CLAUDE.md                      # thin: "@AGENTS.md"
├── .cursor/settings.json          # Cursor reads AGENTS.md + .agents/ natively
├── .mcp.json                      # shared MCP server config (minimal default)
├── .agents/
│   ├── rules/
│   │   ├── shared/                # apply regardless of stack (workflow/git/issue norms)
│   │   ├── python/                # uv, python-best-practices, load-dotenv, library-vs-scripts
│   │   └── react/                 # bun-react, react-best-practices (Vite/TS/Vitest/Biome)
│   └── skills/                    # canonical harness-agnostic dev skills (Cursor reads natively)
├── .claude/
│   ├── settings.json              # hooks (Stop→tests, PreToolUse→permission) + permissions
│   ├── hooks/                     # run-tests-on-stop.sh (stack-aware), claude_permission_hook.sh
│   └── skills  ->  ../.agents/skills   # SINGLE committed directory symlink (Claude Code bridge)
├── .github/
│   ├── workflows/ci.yml           # pre-init: matrix lints+tests BOTH stacks
│   ├── dependabot.yml             # pip + npm + github-actions ecosystems
│   ├── PULL_REQUEST_TEMPLATE.md   # gridium-agent's thorough template
│   └── repo-settings/             # canonical ruleset.json + merge-settings.json
├── Makefile                       # pre-init dispatcher (delegates to both stacks) + shared targets
├── mk/shared.mk                   # shared targets (cc, init, apply_repo_settings, help)
├── README.md                      # contains the interview prompt
├── pyproject.toml                 # root: template-tooling only (pytest for the machinery tests)
├── scripts/
│   ├── init_template.py           # `make init` — promote chosen stack, prune rest (stdlib-only)
│   └── apply_repo_settings.py     # `make apply_repo_settings` — diff+apply via gh api (stdlib-only)
├── tests/template/                # tests for the template machinery itself
└── stacks/
    ├── python/                    # full runnable uv scaffold (pyproject, src/, tests/, Makefile, .python-version)
    └── react/                     # full runnable bun+Vite scaffold (package.json, src/, tests/, Makefile, biome.json, tsconfig, vitest.config)
```

### Post-init (after `make init STACK=python`)

`stacks/`, the unused rules subdir, `scripts/init_template.py`, `tests/template/`,
the root template-tooling `pyproject.toml`, dispatcher remnants, and the README
interview block are gone. The chosen stack's files sit at root; `AGENTS.md`,
`ci.yml`, and `Makefile` are rewritten to the single chosen stack. The result looks
like a clean, finished single-stack repo. `apply_repo_settings.py` +
`.github/repo-settings/` are **kept** so settings can be re-asserted later.

## Shared agent infrastructure

- **Routing model (from gridium-agent):** `CLAUDE.md` imports `@AGENTS.md` (the single
  source of truth); `.cursor/` reads `AGENTS.md` and `.agents/` natively. `AGENTS.md`'s
  `## Rules` section routes every agent to `.agents/rules/`.
- **Rules dir = `.agents/rules/{shared,python,react}/`** (renamed from gridium-agent's
  flat `.agentrules/`). Subdir grouping makes pruning a directory delete. Each rule is a
  Markdown file with `description` + optional `appliesTo` glob frontmatter, mapped by each
  harness to its own mechanism. Renaming the path is text-only (routing table in
  `AGENTS.md` + a few self-references in rule bodies); no code or harness hardcodes the
  path — neither Claude Code nor Cursor auto-loads either path; both rely on `AGENTS.md`
  routing.

### Skill linking — single directory symlink (no conf, no sync script)

The Agent Skills spec (agentskills.io) defines the `SKILL.md` format but **not** a
repo-level directory or per-harness discovery. Discovery is harness-specific:

| Harness | Reads `.agents/skills/` natively? |
|---|---|
| Cursor | Yes — first-class project location (also `.cursor/skills/`, legacy `.claude/skills/`) |
| Claude Code | No — scans only `.claude/skills/` (+ `~/.claude/skills/`, plugins, `--add-dir`); no config to point elsewhere |

Therefore:
- **Canonical:** `.agents/skills/` — real skill folders live here (Cursor reads natively).
- **Claude Code bridge:** `.claude/skills` is a **single committed directory-level
  symlink** → `../.agents/skills`. No conf file, no per-skill symlinks, no sync script.
  Git preserves the symlink through template instantiation.

This **drops** gridium-agent's `sync-shared-skill.sh`,
`conf/symlink_skills_for_claudecode.yaml`, and the `sync_*_skills` Makefile targets.

Known minor caveats (acceptable for a template): Cursor may resolve both
`.agents/skills/` and the `.claude/skills` symlink to the same files — it dedupes by
skill name, so harmless. Claude Code's *live-reload* watcher may not follow the
symlink mid-session; startup discovery does, which is what matters.

## Quality gates + Makefile parity

**Identical target names across both stacks** so muscle memory and CI are uniform.
Each stack's `Makefile` implements the same verbs with its own tooling; shared verbs
live in `mk/shared.mk` (`include`d by each stack Makefile so they survive init).

| Target | Python (uv) | React.ts (bun) |
|---|---|---|
| `make deps` | `uv sync --dev` | `bun install` |
| `make format` | `black .` | `biome format --write` |
| `make lint` | `black --check` + `ruff check` + `mypy` | `biome check` (lint+format) + `tsc --noEmit` |
| `make tests` | `pytest -n auto` (excl. e2e) | `vitest run` |
| `make coverage` | `pytest --cov --cov-fail-under=80` | `vitest run --coverage` (v8, 80% gate) |
| `make security` | `bandit -r` | `bun audit` (dependency CVEs) |
| `make pr_check` | `lint` + `tests` | `lint` + `tests` |

Shared (in `mk/shared.mk`): `make help`, `make cc`
(`caffeinate -di claude --enable-auto-mode --remote-control`), `make init`,
`make apply_repo_settings`.

### Backend stack (mirrors gridium-agent exactly)

Python 3.13.5 (`.python-version`), `uv`. `pyproject.toml`:
- `black` line-length 88.
- `ruff` `extend-select = ["E501","W","D"]`, `extend-ignore = ["D107"]`, numpy
  pydocstyle convention, sensible per-file-ignores for `tests/**` and `scripts/**`.
- `mypy` strict: `disallow_untyped_defs = true`, `plugins = ["pydantic.mypy"]`,
  `files = ["src","scripts","tests"]`.
- `pytest`: `-n auto`, `addopts` excludes `e2e`/`integration` by default; markers
  `e2e` and `integration` defined.
- `pytest-cov` 80% gate; `bandit`.
- Minimal `src/<pkg>/` hello module + a passing test prove the wiring.

### Frontend stack (new Gridium org default)

Vite + React + TypeScript on `bun`. `biome.json` configured to match **snapmeter's
formatting output** so a snapmeter dev sees identical formatting under a faster engine:

```jsonc
{
  "formatter": { "indentStyle": "space", "indentWidth": 2, "lineWidth": 80 },
  "javascript": {
    "formatter": {
      "quoteStyle": "single",        // snapmeter singleQuote: true
      "semicolons": "always",        // Prettier default snapmeter keeps
      "trailingCommas": "all",       // snapmeter trailingComma: "all"
      "arrowParentheses": "always"   // snapmeter arrow-parens: always
    }
  },
  "linter": { "enabled": true, "rules": { "recommended": true } }
}
```

Plus `tsconfig.json` (strict), `vitest.config.ts` (jsdom + Testing Library, v8
coverage 80%), a sample `App.tsx` + component + passing Vitest test. Component files
PascalCase (`Button.tsx`).

**Deliberate divergences from snapmeter** (sanctioned by speed/modernization goals):
Biome instead of ESLint(airbnb-base)+Prettier; `bun` instead of npm/Bower + Node 18
`.nvmrc`; React.ts/Vite + Vitest instead of Ember/Handlebars/QUnit; PascalCase
component files instead of Ember's kebab-case (React tooling expects this — not a
"mostly equal" case); `AGENTS.md` routing instead of snapmeter's single `.cursorrules`.

## CI

GitHub Actions `ci.yml`. **Pre-init:** two parallel jobs — `python` (setup-uv,
`make -C stacks/python pr_check`/`coverage`/`security`) and `react` (setup-bun,
`make -C stacks/react pr_check`/`coverage`/`security`). Both green proves "both stacks
runnable out of the box." **`make init` rewrites `ci.yml`** to just the chosen stack's
jobs (single-stack, gridium-agent-style lint/test/security). `.circleci` is **dropped**
(vestigial "say-hello" stub). `dependabot.yml` covers `pip` + `npm` + `github-actions`;
init prunes the unused ecosystem.

**Stop hook** (`run-tests-on-stop.sh`) is stack-aware: detects changed source file
types and runs `make format && make tests` for the relevant stack; pre-init it runs
the template-machinery tests when `scripts/`/`tests/template/` change. Init simplifies
it to the chosen stack.

## Init flow, interview prompt, repo-settings

### Repo-settings artifact (`.github/repo-settings/`)

Two checked-in files capturing the template's canonical settings (pulled from
`Gridium/agentic-ai-powered-repo` live):

- **`ruleset.json`** — the `main` ruleset, sanitized (strip `id`/`node_id`/timestamps/
  `source`/`_links`; keep `name`,`target`,`enforcement`,`conditions`,`rules`,
  `bypass_actors`): block `deletion` + `non_fast_forward`; `pull_request` rule with
  `required_review_thread_resolution: true`, `dismiss_stale_reviews_on_push: true`,
  `required_approving_review_count: 0`, `allowed_merge_methods: ["squash"]`;
  `copilot_code_review` (`review_on_push: false`, `review_draft_pull_requests: false`).
- **`merge-settings.json`** — `allow_squash_merge: true`, `allow_merge_commit: false`,
  `allow_rebase_merge: false`, `allow_auto_merge: true`, `delete_branch_on_merge: true`,
  `squash_merge_commit_title: "COMMIT_OR_PR_TITLE"`,
  `squash_merge_commit_message: "COMMIT_MESSAGES"`.

### `apply_repo_settings.py` (`make apply_repo_settings`)

stdlib + `gh` subprocess; no deps. Resolves the current repo via `gh repo view`, reads
desired settings, fetches current ruleset + merge prefs, **prints a diff**, and unless
`--yes` is passed **asks for confirmation before applying**. Apply = PUT existing `main`
ruleset (matched by name) or POST a new one; PATCH merge prefs. Idempotent — exits
"already aligned" with no changes when in sync. Kept in the spawned repo.

### `init_template.py` (`make init STACK=… PROJECT_NAME=… DESCRIPTION=…`)

Designed as a pure function `initialize(root, stack, project_name, description,
apply_settings)` — `root` injectable so tests run in a temp tree; git/gh calls gated.
stdlib-only. Deterministic transform:

1. **Guard** — refuse if `stacks/` already absent (already initialized); reject invalid
   `STACK` (must be `python` or `react`).
2. **Promote** — move `stacks/<STACK>/*` to root (prefer `git mv` for clean staging);
   the stack's `Makefile` becomes root `Makefile` (still `include`s `mk/shared.mk`).
3. **Prune** — `rm -rf stacks/` (drops the other stack), remove `.agents/rules/<other>`,
   flatten the `<STACK>` rules alongside `shared`, drop the unused `dependabot.yml`
   ecosystem.
4. **Rewrite generated files** — `AGENTS.md` (collapse dual-stack router → chosen stack;
   fill `PROJECT_NAME`/`DESCRIPTION` placeholders); `ci.yml` (chosen job only);
   `README.md` (strip interview block → normal seeded project README + stack quickstart);
   `pyproject.toml`/`package.json` name; simplify the Stop hook.
5. **Apply settings** — invoke `apply_repo_settings.py` (with confirm) unless
   `--skip-settings`.
6. **Self-destruct machinery** — remove `scripts/init_template.py`, `tests/template/`,
   the root template-tooling `pyproject.toml`, dispatcher remnants. Keep
   `apply_repo_settings.py` + `.github/repo-settings/`.
7. **Print next steps** — the interview agent then stages, commits, and tells the user
   to push.

### README interview prompt (required)

A fenced, copy-paste prompt block at the top of `README.md`, harness-agnostic. It
instructs the agent to:

- **Prefer the harness's native structured-interview tooling** (e.g. Claude Code's
  `AskUserQuestion`, Cursor's equivalent) over free-text Q&A, falling back to plain
  prompts only when no such tool exists.
- **Interview one question at a time:** frontend or backend? → confirm/override
  language + framework, seeded with **Gridium org defaults** (backend = Python 3.13/uv +
  black/ruff/mypy/pytest/bandit; frontend = Vite/React/TS/bun +
  Biome[snapmeter formatting]/Vitest/tsc) → project name + one-line description → confirm
  the target repo for settings.
- **Then run the terminal actions:** `make init STACK=… PROJECT_NAME=… DESCRIPTION=…` →
  `make apply_repo_settings` (diff + confirm) → stage + initial commit → tell the user to
  push.
- **Scope note:** the two shipped stacks are the supported choices today; other
  languages/frameworks are a future template extension.

## Testing strategy

The template is mostly config + self-deleting machinery. Tests:

1. **Template-machinery unit tests** (`tests/template/`, run by the root tooling
   `pyproject` via pytest):
   - `test_init_template.py` — copy the template tree into `tmp_path`, run
     `initialize(root=tmp, stack="python", …, apply_settings=False)`, assert the full
     post-init shape: `stacks/` gone, react rules gone, root has `pyproject`/`src`/`tests`,
     `Makefile` includes `mk/shared.mk`, `AGENTS.md` has zero react refs + `PROJECT_NAME`
     filled, `ci.yml` has only the python job, README interview block stripped, init script
     self-removed. Mirror for `stack="react"`. Plus guard tests (refuse when already
     initialized; reject invalid `STACK`).
   - `test_apply_repo_settings.py` — diff logic with injected fake current-state JSON;
     assert the PUT-vs-POST decision and the no-op-when-aligned path. `gh` calls
     injected/mocked — no live API.
2. **Each stack ships its own green tests** — a pytest sample (Python) and a Vitest
   sample (React) that become the spawned repo's starter tests.
3. **E2E (orchestrator-owned, build-from-issue Step 6):** in a temp clone, actually run
   `make init STACK=python … && make deps && make pr_check` → green; repeat for react
   (`--skip-settings`, no live gh mutation). Proves the real transform + both toolchains
   end-to-end. Heavy (installs uv + bun) → on-demand, not every push.

Root CI runs the machinery unit tests + both stacks' `pr_check`.

## Carried from gridium-agent (generic best practice)

- Routing model: `AGENTS.md` + `CLAUDE.md` import + `.cursor/`.
- Rules — shared: default-to-shareable-rules, checkpoint-commits, never-delete-only-close,
  no-orphan-issues, issue-card-brevity, gh-issue-dependencies, worktree-for-planning,
  bugbot-auto-review, fetch-library-docs-first, fail-hard-not-warn, use-bundled-skill-scripts.
- Rules — python: uv-python, python-best-practices, load-dotenv-first, library-vs-scripts.
- Rules — react (NEW): bun-react, react-best-practices (Vite/TS/Vitest/Biome + snapmeter
  formatting note).
- Skills → `.agents/skills/`: build-from-issue, plan-issues, resolve-pr-concerns, pr-check,
  review-skill, run-tests.
- Hooks: stack-aware run-tests-on-stop + claude_permission_hook; trimmed `settings.json`.
  CI pattern, dependabot, PR template, `.gitignore` essentials.

## Dropped (domain-specific to gridium-agent)

ECM skills, langfuse skill + observability, neo4j/ontology, citations, pipeline,
`conf/llms.yaml`, Azure Foundry env, `litellm-suppress-debug` rule, domain scripts/tests,
notebooks — and the `.circleci` stub. Plus gridium-agent's skill-sync machinery
(`sync-shared-skill.sh`, `conf/symlink_skills_for_claudecode.yaml`, `sync_*` targets).

## Out of scope (future template extensions)

- Languages/frameworks beyond the two shipped stacks.
- GitHub label/project-board bootstrap.
- Windows symlink support (Gridium dev = darwin, CI = ubuntu).
