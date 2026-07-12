---
description: When you learn a durable, project-relevant convention/fact/workflow, default to authoring a shareable rule in .agents/rules/ rather than a local-only agent memory.
alwaysApply: true
---

# Default to shareable rules, not local memories

When you learn something durable and project-relevant — a coding convention, a
workflow norm, a non-obvious project fact — **author or update a rule in
`.agents/rules/`** (committed, visible to every dev) by default, instead of saving a
local-only agent memory.

**Why:** Local agent memories live on one developer's machine and never reach
teammates. Conventions captured only as personal memories don't travel; a new dev
(or a fresh agent) operates without them. `.agents/rules/` is the shared mechanism —
it ships with the repo.

**The test**
- *Would another dev on this repo benefit from this?* → **rule** in `.agents/rules/`.
- *Is it only my personal taste, working rhythm, or machine setup?* → fine as a
  **local memory** (don't commit it).

**How to apply**
- Project-level convention/fact/workflow → create `.agents/rules/<kebab-topic>.md`
  with the standard frontmatter (`description`, optional `appliesTo`,
  `alwaysApply`). One concept per file. De-personalize: state it as a team rule,
  not "X asked me to…".
- Updating existing guidance → edit the relevant `.agents/rules/` file rather than
  adding a parallel memory that drifts from it.
- Dev-specific preference (editor, commit-message taste, personal cadence) → keep
  it local; it's not a team rule.
- When unsure, lean toward a shareable rule — sharing is the default.
