# Harness-Agnostic Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `.agents/skills/**/SKILL.md` resolve cleanly in every harness (not just Claude Code) by normalizing Claude-only path/env references and documenting the portability conventions in a shared rule.

**Architecture:** Documentation-only change. Add one `alwaysApply` shared rule that documents four portability axes; normalize the two skills that carry genuine Claude-only path/env references (`review-skill`, `build-from-issue`); wire the rule's discoverability into `AGENTS.md`. Tool names and portable frontmatter are kept as-is per the approved spec — the rule documents *why*.

**Tech Stack:** Markdown docs; `.agents/rules/` shared-rule mechanism; `review-skill`'s bundled `scripts/validate.py` (run via `uv run python` per `uv-python.md`).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-03-harness-agnostic-skills-design.md` — authoritative.
- Do **not** rewrite inline tool names (`AskUserQuestion`, `TodoWrite`, `Task`, `Glob`, `Grep`) in prose or `allowed-tools`. Keep them; the rule documents the mapping.
- Do **not** rewrite portable frontmatter (`allowed-tools` incl. `Bash(cmd:*)` scoping, `disable-model-invocation`).
- When naming a per-harness dir (`.claude/skills/`), it must appear only *alongside* the canonical `.agents/skills/`, never as the sole location.
- The dependabot companion track is **out of scope for this plan** (separate ops).
- Run the validator with `uv run python`, not bare `python3` (per `.agents/rules/python/uv-python.md`).
- Commit messages end with the repo's `Co-Authored-By` / `Claude-Session` trailers.

---

### Task 1: Add the shared portability rule

**Files:**
- Create: `.agents/rules/shared/harness-agnostic-skills.md`

**Interfaces:**
- Consumes: nothing.
- Produces: the file `.agents/rules/shared/harness-agnostic-skills.md`, referenced by name in Task 2 and Task 4.

- [ ] **Step 1: Write the failing check**

Run: `test -f .agents/rules/shared/harness-agnostic-skills.md && echo FOUND || echo MISSING`
Expected: `MISSING`

- [ ] **Step 2: Create the rule file**

Create `.agents/rules/shared/harness-agnostic-skills.md` with exactly this content:

```markdown
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
```

- [ ] **Step 3: Verify the file exists and has valid frontmatter**

Run: `test -f .agents/rules/shared/harness-agnostic-skills.md && head -3 .agents/rules/shared/harness-agnostic-skills.md`
Expected: prints the file's opening `---`, the `description:` line, and `alwaysApply: true`.

- [ ] **Step 4: Commit**

```bash
git add .agents/rules/shared/harness-agnostic-skills.md
git commit -m "rules: add harness-agnostic-skills shared rule (#4)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0189L2goAQpMi97TSR1CnEMA"
```

---

### Task 2: Normalize `review-skill/SKILL.md`

**Files:**
- Modify: `.agents/skills/review-skill/SKILL.md:27-29` and `:40-42`

**Interfaces:**
- Consumes: the rule file from Task 1 (referenced by path).
- Produces: nothing consumed downstream.

- [ ] **Step 1: Write the failing check**

Run: `grep -n '\.agents/skills/' .agents/skills/review-skill/SKILL.md || echo MISSING`
Expected: `MISSING` (the canonical dir is not yet named in this skill).

- [ ] **Step 2: Edit the Step-1 resolution list (`:27-29`)**

Replace these three lines:

```markdown
- A path to a skill directory (e.g., `.claude/skills/my-skill/`)
- A path to a SKILL.md file (e.g., `.claude/skills/my-skill/SKILL.md`)
- A skill name — resolve it by searching `.claude/skills/`, `~/.claude/skills/`, and the current project
```

with:

```markdown
- A path to a skill directory (e.g., `.agents/skills/my-skill/` — canonical; a per-harness dir like `.claude/skills/my-skill/` also works)
- A path to a SKILL.md file (e.g., `.agents/skills/my-skill/SKILL.md`)
- A skill name — resolve it by searching `.agents/skills/` (canonical), any per-harness dirs (`.claude/skills/`, `~/.claude/skills/`), and the current project
```

- [ ] **Step 3: Edit the validator-resolution note (`:40-42`)**

Replace these three lines:

```markdown
Resolve `scripts/validate.py` relative to this skill's own directory — run it from
there, or prefix it with the skill's path (Claude Code exposes that as
`${CLAUDE_SKILL_DIR}`; other harnesses resolve skill-relative paths their own way).
```

with:

```markdown
Resolve `scripts/validate.py` relative to this skill's own directory — run it from
there, or prefix it with the skill's path (Claude Code exposes that as
`${CLAUDE_SKILL_DIR}`; other harnesses resolve skill-relative paths their own way).
See `.agents/rules/shared/harness-agnostic-skills.md` for the full convention.
```

- [ ] **Step 4: Verify the canonical dir is now named and the rule is referenced**

Run: `grep -c '\.agents/skills/' .agents/skills/review-skill/SKILL.md && grep -c 'harness-agnostic-skills.md' .agents/skills/review-skill/SKILL.md`
Expected: first count ≥ 3, second count = 1.

- [ ] **Step 5: Verify the skill still passes its own validator**

Run: `cd .agents/skills/review-skill && uv run python scripts/validate.py . ; cd -`
Expected: validator reports PASS / no structural errors for `review-skill`.

- [ ] **Step 6: Commit**

```bash
git add .agents/skills/review-skill/SKILL.md
git commit -m "review-skill: name .agents/skills/ canonical; link portability rule (#4)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0189L2goAQpMi97TSR1CnEMA"
```

---

### Task 3: Normalize `build-from-issue/SKILL.md`

**Files:**
- Modify: `.agents/skills/build-from-issue/SKILL.md:299`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing consumed downstream.

- [ ] **Step 1: Write the failing check**

Run: `sed -n '299p' .agents/skills/build-from-issue/SKILL.md | grep -q '\.agents/skills/' && echo HAS || echo MISSING`
Expected: `MISSING`

- [ ] **Step 2: Edit the doc-locations example (`:299`)**

Replace this line:

```markdown
- Check for any other agent-facing docs in the repo (e.g., `CLAUDE.md`, `skills/`, `.claude/skills/`) and update as relevant.
```

with:

```markdown
- Check for any other agent-facing docs in the repo (e.g., `CLAUDE.md`, `.agents/skills/` (canonical; read via the `.claude/skills` symlink in Claude Code)) and update as relevant.
```

- [ ] **Step 3: Verify the canonical dir is now named on that line**

Run: `grep -n '\.agents/skills/' .agents/skills/build-from-issue/SKILL.md`
Expected: at least one match, including the edited "other agent-facing docs" line.

- [ ] **Step 4: Commit**

```bash
git add .agents/skills/build-from-issue/SKILL.md
git commit -m "build-from-issue: name .agents/skills/ canonical in doc-locations example (#4)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0189L2goAQpMi97TSR1CnEMA"
```

---

### Task 4: Wire discoverability into `AGENTS.md`

**Files:**
- Modify: `AGENTS.md` `## Skills` section (lines ~62-65)

**Interfaces:**
- Consumes: the rule file from Task 1 (referenced by name).
- Produces: nothing consumed downstream.

**Note:** The `## Rules` table collapses all shared rules into the single
`.agents/rules/shared/*.md` row (no shared rule is listed individually), so the new
rule is already routed by that row. The meaningful, skill-specific wiring is a pointer
in the `## Skills` section — this follows the repo's existing table pattern rather than
adding an inconsistent one-off row. This satisfies AC #3 (the convention is documented
in the shared rule and discoverable from `AGENTS.md`).

- [ ] **Step 1: Write the failing check**

Run: `grep -q 'harness-agnostic-skills' AGENTS.md && echo HAS || echo MISSING`
Expected: `MISSING`

- [ ] **Step 2: Edit the `## Skills` section**

Replace these two lines (currently lines ~64-65):

```markdown
Reusable agent workflows live in `.agents/skills/` (canonical). Claude Code reads
them through the `.claude/skills` symlink; Cursor reads `.agents/skills/` natively.
```

with:

```markdown
Reusable agent workflows live in `.agents/skills/` (canonical). Claude Code reads
them through the `.claude/skills` symlink; Cursor reads `.agents/skills/` natively.
When writing or editing a skill, keep it harness-agnostic — see
`.agents/rules/shared/harness-agnostic-skills.md` (canonical paths, skill-root-relative
bundled files, and which `SKILL.md` frontmatter is portable vs Claude-Code-only).
```

- [ ] **Step 3: Verify the pointer landed**

Run: `grep -n 'harness-agnostic-skills' AGENTS.md`
Expected: one match in the `## Skills` section.

- [ ] **Step 4: Commit**

```bash
git add AGENTS.md
git commit -m "AGENTS.md: point the Skills section at the harness-agnostic-skills rule (#4)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0189L2goAQpMi97TSR1CnEMA"
```

---

### Task 5: Full audit sweep (acceptance substrate)

**Files:** none modified — verification only.

**Interfaces:**
- Consumes: all edits from Tasks 1-4.
- Produces: the evidence the Step 7 acceptance audit will cite.

- [ ] **Step 1: Every `.claude/skills` reference in a SKILL.md also names `.agents/skills/`**

Run:
```bash
for f in .agents/skills/review-skill/SKILL.md .agents/skills/build-from-issue/SKILL.md; do
  echo "== $f =="; grep -nE '\.claude/skills|\.agents/skills' "$f"
done
```
Expected: in each file, no `.claude/skills` reference stands alone — the canonical `.agents/skills/` is named in the same context.

- [ ] **Step 2: `${CLAUDE_SKILL_DIR}` is framed as one harness's example**

Run: `grep -n 'CLAUDE_SKILL_DIR' .agents/skills/review-skill/SKILL.md`
Expected: the one match is the hedged prose ("Claude Code exposes that as … other harnesses resolve … their own way"), now followed by the rule cross-reference.

- [ ] **Step 3: Rule exists, is `alwaysApply`, and is linked from `AGENTS.md`**

Run:
```bash
head -3 .agents/rules/shared/harness-agnostic-skills.md
grep -n 'harness-agnostic-skills' AGENTS.md .agents/skills/review-skill/SKILL.md
```
Expected: frontmatter shows `alwaysApply: true`; the rule is referenced from both `AGENTS.md` and `review-skill/SKILL.md`.

- [ ] **Step 4: Both edited skills pass the validator**

Run:
```bash
for s in review-skill build-from-issue; do
  echo "== $s =="; (cd ".agents/skills/$s" && uv run python "$OLDPWD/.agents/skills/review-skill/scripts/validate.py" .)
done
```
Expected: PASS / no structural errors for both.

- [ ] **Step 5: No commit** — verification-only task; nothing to commit.

---

## Self-Review

**Spec coverage:**
- Deliverable A (new rule) → Task 1. ✅
- Deliverable B (review-skill :27-29, :41-42) → Task 2. ✅
- Deliverable C (build-from-issue :299) → Task 3. ✅
- Deliverable D (AGENTS.md wiring) → Task 4 (adapted to the table's collapse pattern; pointer in Skills section). ✅
- Per-skill audit verdict "no change" for plan-issues/pr-check/run-tests/resolve-pr-concerns → no task needed; recorded in the spec; Task 5 confirms no new violations. ✅
- Verification (audit grep, rule linked, validator) → Task 5. ✅

**Placeholder scan:** No TBD/TODO; every edit shows exact before/after content; every check shows the exact command and expected output. ✅

**Type consistency:** N/A (docs). Rule filename `harness-agnostic-skills.md` used identically in Tasks 1, 2, 4, 5. ✅

**Out of scope confirmed absent:** no dependabot task; no frontmatter rewrites; no touching of untracked `.validation-result.json`. ✅
