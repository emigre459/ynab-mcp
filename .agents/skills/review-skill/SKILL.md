---
name: review-skill
description: |
  Review and validate a skill for correctness, quality, and adherence
  to best practices. Use when the user asks to review a skill, validate a
  skill, check a skill, audit a SKILL.md, or verify skill quality. Runs
  automated structural checks and performs qualitative analysis of description
  quality, instruction clarity, progressive disclosure, and security.
allowed-tools: Bash(uv run python:*) Read Glob Grep
---

# Review Skill

Validate a skill directory against the Agent Skills specification and best-practice guidelines.

## References

| File | Contents | When to consult |
|------|----------|-----------------|
| `scripts/validate.py` | Automated structural validator | Run first on every review |

## Instructions

### Step 1: Identify the target skill

If the user provides a path, use it. Otherwise, ask which skill to review. Accept either:
- A path to a skill directory (e.g., `.agents/skills/my-skill/` — canonical; a per-harness dir like `.claude/skills/my-skill/` also works)
- A path to a SKILL.md file (e.g., `.agents/skills/my-skill/SKILL.md`)
- A skill name — resolve it by searching `.agents/skills/` (canonical), any per-harness dirs (`.claude/skills/`, `~/.claude/skills/`), and the current project

### Step 2: Run the automated validator

Run the validation script (bundled in this skill at `scripts/validate.py`,
referenced relative to the skill root per the Agent Skills spec) against the target:

```
uv run python scripts/validate.py <path-to-skill-directory>
```

Resolve `scripts/validate.py` relative to this skill's own directory — run it from
there, or prefix it with the skill's path (Claude Code exposes that as
`${CLAUDE_SKILL_DIR}`; other harnesses resolve skill-relative paths their own way).
See `.agents/rules/shared/harness-agnostic-skills.md` for the full convention.

Capture all output. The script checks structural rules:
- File structure (folder naming, SKILL.md casing, no README.md)
- YAML frontmatter (name constraints, description constraints, no XML tags, reserved words)
- Body size (line count, character count)
- References (linked from SKILL.md, no cross-references, TOC for long files)
- Scripts (existence, executability)
- Security (hardcoded secrets, backslash paths)

The script exits 0 on success, 1 if any checks fail. It also writes a `.validation-result.json` file in the skill directory.

### Step 3: Perform qualitative review

Read the SKILL.md file and evaluate these criteria that cannot be checked programmatically. For each, give a brief assessment (pass / needs improvement) with specific, actionable feedback.

**Description quality:**
- Does the description follow the `[what it does] + [when to use it] + [key capabilities]` format?
- Does it include specific trigger keywords or phrases a user would actually say?
- Is it written in third person? (not "I" or "You")
- Is it specific enough to trigger reliably without over-triggering?
- Would Claude be able to distinguish this skill from other installed skills based on the description alone?

**Instruction quality:**
- Are instructions specific and actionable? (not vague like "validate the data")
- Are critical instructions near the top of the body?
- Does the skill avoid explaining things LLMs already know?
- Is every paragraph earning its token cost?
- Are examples provided with clearly delineated inputs and outputs?
- Is output format specified where consistency matters?
- If the instructions reference ARGUMENTS, does the frontmatter include an `argument-hint` field?
- Do the instructions directly reference multiple items in an argument list? Such references can be brittle, and arguments should be kept simple.

**Progressive disclosure:**
- Is the SKILL.md body appropriately sized (under 500 lines)?
- Is detailed content split into reference files rather than inlined?
- If references exist, are they linked from a reference table in the body?
- Are references one level deep (no cross-references between reference files)?

**Degrees of freedom:**
- Does the skill match specificity to task fragility? (tight guardrails for fragile operations, loose guidance for creative tasks)
- Does it provide defaults with escape hatches rather than open-ended choices?

**Error handling:**
- Are common failure modes documented?
- Does the skill include troubleshooting guidance or validation steps?
- If scripts exist, do they provide helpful error messages?

**Security:**
- No hardcoded secrets, API keys, or credentials
- No sensitive data in examples
- File paths use forward slashes

### Step 4: Present the report

Present findings in this format:

```
## Skill Review: <skill-name>

### Automated checks
<summary of validate.py output — pass/fail/warn counts>
<list any failures or warnings>

### Qualitative review

#### Description quality
<assessment>

#### Instruction quality
<assessment>

#### Progressive disclosure
<assessment>

#### Degrees of freedom
<assessment>

#### Error handling
<assessment>

#### Security
<assessment>

### Summary
<overall assessment: ready / needs work>
<prioritized list of improvements, most impactful first>
```

### Step 5: Offer to fix

If there are failures or actionable improvements, ask the user if they'd like you to fix the issues. If yes, make the edits and re-run the validator to confirm.

## Edge cases

- **Skill has no references/, scripts/, or assets/ folders**: This is fine for simple skills. Skip those sections in the review rather than flagging their absence.
- **Very large SKILL.md (500+ lines)**: Flag this prominently and recommend specific content to move into reference files.
- **Non-standard frontmatter fields**: The spec allows vendor-specific extensions. Don't flag unknown fields as errors — just note them.
- **allowed-tools as a list vs. space-delimited string**: Both formats are valid depending on the platform. Don't flag either as wrong.
