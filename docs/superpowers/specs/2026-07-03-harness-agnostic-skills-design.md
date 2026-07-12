# Make `.agents/skills/` harness-agnostic — design

**Issue:** [#4 — Make .agents/skills/ harness-agnostic (drop Claude-Code-only path assumptions)](https://github.com/Gridium/agentic-ai-powered-repo/issues/4)
**Date:** 2026-07-03
**Status:** Approved (brainstorming) → ready for implementation plan

## Problem

Skills live in the harness-agnostic canonical dir `.agents/skills/` (Claude Code
reads them through the `.claude/skills` symlink; Cursor reads `.agents/skills/`
natively). Several skills still carry Claude-Code-only assumptions in their prose:
hard-coded `.claude/skills/` paths and a `${CLAUDE_SKILL_DIR}` reference. They work
in Claude Code but read incorrectly in Cursor / other harnesses. This is a
follow-up from Cursor Bugbot finding **K** on #2.

The fix is documentation-only: normalize the genuinely-Claude-only path references,
audit every skill for harness assumptions, and document — once, in a shared rule —
the conventions each harness follows so future skills stay portable.

## Scope decision: prose vs. frontmatter vs. false positives

The audit surfaced three distinct classes of "Claude-specific" content. They are
**not** treated the same way, and the distinction was the main design decision.

### 1. Path / env references — normalize (the real bug)

| Location | Issue | Fix |
|----------|-------|-----|
| `review-skill/SKILL.md:27-29` | resolution examples name only `.claude/skills/`, `~/.claude/skills/` | add `.agents/skills/` as the canonical dir alongside the per-harness examples |
| `review-skill/SKILL.md:41-42` | `${CLAUDE_SKILL_DIR}` presented as the way to prefix the skill path | keep it as *one harness's* example of the skill-root-relative norm; cross-reference the new rule |
| `build-from-issue/SKILL.md:299` | `.claude/skills/` as an example doc location | add `.agents/skills/` alongside it |

### 2. Tool names — document the mapping, do **not** rewrite

Claude-specific tool *names* (`AskUserQuestion` ×~25, `TodoWrite` ×1, `Task`) appear
in skill **prose** and in `plan-issues`' `allowed-tools` frontmatter. Decision
(user-approved): **keep them inline.** They are the actual Claude Code interaction
contract; blanket-replacing them with generic phrasing would degrade the primary
harness and add noise. Instead, the new shared rule states once that Claude-specific
tool names denote the Claude Code tool and other harnesses substitute their
equivalent (interactive user-prompt, todo tracker, subagent dispatch).

### 3. Frontmatter portability — verified against the spec, no rewrite needed

Verified against the Agent Skills open standard (Context7 `/oakoss/agent-skills`):

- **`allowed-tools` is part of the open standard and portable**, *including* the
  `Bash(command:*)` glob-scoping syntax. So `pr-check`'s `Bash(make pr_check)` and
  `review-skill`'s `Bash(python:*)` are spec-compliant, **not** Claude-only.
- **Portable optional fields:** `license`, `compatibility`, `metadata`,
  `allowed-tools`.
- **Claude-Code-specific extensions:** `disable-model-invocation`, `user-invocable`,
  `model`, `context`, `agent`, `hooks`, `argument-hint`. Other harnesses ignore
  unknown fields.

The only genuinely Claude-specific frontmatter in our skills is the tool names
`AskUserQuestion` / `Task` inside `plan-issues`' `allowed-tools`, and
`disable-model-invocation: true` in `pr-check` / `run-tests`. **All three are
non-breaking** (unknown fields ignored; unknown tool names simply not granted
elsewhere) and removing them would degrade Claude Code. **Verdict: no rewrite.** The
rule documents the portability convention so this stays a conscious choice.

### 4. False positives — leave alone

`Anthropic` / `claude-code-review` / `pull_request_target` / OIDC references in
`resolve-pr-concerns` describe the project's real CI and API, not harness path
assumptions.

## Per-skill audit verdict (AC #1 — every skill covered)

| Skill | Verdict |
|-------|---------|
| `review-skill` | **Edit** — `.claude/skills/` paths (:27-29) + `${CLAUDE_SKILL_DIR}` (:41-42). Frontmatter `Bash(python:*) Read Glob Grep` is portable — no change. |
| `build-from-issue` | **Edit** — `.claude/skills/` example doc location (:299). No frontmatter concerns. |
| `plan-issues` | **No change** — only Claude-specific surface is prose tool names + `allowed-tools` tool names (`AskUserQuestion`, `Task`); both portable-safe per §2/§3. |
| `pr-check` | **No change** — `Bash(...)` scoping portable; `disable-model-invocation` is a safe Claude extension. |
| `run-tests` | **No change** — same as `pr-check`. |
| `resolve-pr-concerns` | **No change** — only prose tool names + false-positive CI/API references. |

## Deliverables

### A. New shared rule — `.agents/rules/shared/harness-agnostic-skills.md` (AC #3)

`alwaysApply: true`. Documents four axes so future skills stay portable:

1. **Skill-root-relative paths** — reference bundled files (scripts, references)
   relative to the skill's own directory per the Agent Skills spec. Claude Code
   exposes the skill dir as `${CLAUDE_SKILL_DIR}`; other harnesses resolve
   skill-relative paths their own way. Run bundled scripts *from* the skill root.
2. **Canonical location** — `.agents/skills/` is canonical; Claude Code reads it via
   the `.claude/skills` symlink, Cursor reads it natively. Skill prose must name
   `.agents/skills/`; per-harness dirs (`.claude/skills/`) may appear only as
   examples *alongside* it, never as the sole location.
3. **Tool-name mapping** — Claude-specific tool names (`AskUserQuestion`,
   `TodoWrite`, `Task`, `Glob`, `Grep`) denote the Claude Code tool; other harnesses
   substitute their equivalent. Names are kept as-is in prose and `allowed-tools`.
4. **Frontmatter portability** — portable fields: `name`, `description`,
   `allowed-tools` (incl. `Bash(cmd:*)` scoping), `license`, `compatibility`,
   `metadata`. Claude-Code-only extensions (ignored elsewhere, safe to keep):
   `disable-model-invocation`, `user-invocable`, `model`, `context`, `agent`,
   `hooks`, `argument-hint`.

### B. `review-skill/SKILL.md` edits (AC #1 + #2)
Normalize :27-29 and :41-42 per §1; cross-reference the new rule.

### C. `build-from-issue/SKILL.md` edit (AC #1 + #2)
Normalize :299 per §1.

### D. `AGENTS.md` wiring (AC #3)
Add the new rule to the `## Rules` table; add a one-line pointer in the `## Skills`
section (currently lines ~62-65).

## Out of scope

- Untracked `.validation-result.json` artifacts (local scratch; stale `gridium-agent`
  path; not git-tracked).
- The ~27 inline tool-name references (kept per §2; covered by the rule).
- Rewriting portable frontmatter (§3).

## Companion track (issue #4, separate execution)

Per the owner's comment, issue #4 also folds in "update all dependabot PRs." That is
**dependency-ops, not part of this docs design** — the 13 open Dependabot PRs are
separate PRs against `main` and cannot live on this branch. It is executed as its own
track after the docs PR lands: drive the 10 live PRs to merge (minors/patches first,
then the major bumps with CI green), and close the 3 stale `npm_and_yarn` orphans
(#3/#5/#8 — react is `bun`-only, so they cannot apply). The current `dependabot.yml`
is already correct; no config change needed. This spec does not design that track;
it is tracked on the issue card's acceptance criteria.

## Verification (feeds the Step 6 E2E / acceptance audit)

1. Re-run the audit grep: every `.claude/skills` path in a `SKILL.md` also names
   `.agents/skills/`; every `${CLAUDE_SKILL_DIR}` is framed as one harness's example
   of the skill-root-relative norm.
2. New rule exists, is `alwaysApply: true`, and is linked from `AGENTS.md`.
3. Run `review-skill`'s bundled validator (`scripts/validate.py`) against each
   edited skill — must pass.
