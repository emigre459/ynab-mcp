---
description: Keep skills in .agents/skills/ portable across harnesses — canonical paths, skill-root-relative bundled files, and which SKILL.md frontmatter is portable vs Claude-Code-only.
alwaysApply: true
---

# Keep skills harness-agnostic

Skills live in the canonical dir `.agents/skills/` and must resolve cleanly in every
harness (Claude Code, Cursor, …), not just Claude Code. Follow these four conventions
when writing or editing any `SKILL.md`.

## 1. Reference bundled files by skill-root-relative path

Reference a skill's own bundled files (scripts, `references/`, assets) **relative to
the skill's root directory**, per the Agent Skills spec — e.g. `scripts/validate.py`,
not an absolute or harness-specific path. Run bundled scripts *from* the skill root.

Claude Code exposes the skill's directory as `${CLAUDE_SKILL_DIR}`; other harnesses
resolve skill-relative paths their own way. Name `${CLAUDE_SKILL_DIR}` only as *one
harness's* example of the general convention, never as the required mechanism.

## 2. Name `.agents/skills/` as the canonical location

`.agents/skills/` is canonical. Claude Code reads it through the `.claude/skills`
symlink; Cursor reads `.agents/skills/` natively. In skill prose, name
`.agents/skills/`. Per-harness dirs like `.claude/skills/` or `~/.claude/skills/` may
appear only as examples *alongside* the canonical dir — never as the sole location.

## 3. Claude-specific tool names denote the harness equivalent

Tool names like `AskUserQuestion`, `TodoWrite`, `Task`, `Glob`, `Grep` are Claude
Code's names. Keep them as-is in prose and in `allowed-tools` — they are the actual
Claude Code contract, and rewriting them to generic phrasing degrades the primary
harness. Other harnesses read them as "the equivalent capability" (interactive
user-prompt, todo tracker, subagent dispatch, file search). Unknown tool names in
`allowed-tools` are simply not granted elsewhere — harmless.

## 4. Know which frontmatter is portable

Per the Agent Skills open standard:

- **Portable** (safe everywhere): `name`, `description`, `allowed-tools` (including
  the `Bash(command:*)` glob-scoping syntax), `license`, `compatibility`, `metadata`.
- **Claude-Code-only extensions** (other harnesses ignore unknown fields, so these
  are safe to keep but non-portable): `disable-model-invocation`, `user-invocable`,
  `model`, `context`, `agent`, `hooks`, `argument-hint`.

Prefer portable fields. Use a Claude-only extension only when it earns its keep in
Claude Code; never rely on it being honored elsewhere.
