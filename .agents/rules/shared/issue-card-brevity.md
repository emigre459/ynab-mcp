---
description: GitHub issue cards — terse grouped bullet checklists a human can scan in under a minute, still detailed enough to build from. Long rationale goes to spec docs.
alwaysApply: true
---

# Issue-card brevity

GitHub issues should be detailed enough for an agent to build from, but brief
enough to review in well under a minute. Default to grouped bullet checklists;
skip rationale paragraphs unless preserving a non-obvious, load-bearing decision.

**How to apply**
- Structure: 1–2 line summary; scope as a flat bullet checklist; brief non-goals;
  brief done-criteria.
- Move long-form rationale to a spec doc in `docs/superpowers/specs/`, then link it
  from the issue — don't inline it in the body.
- Include approach/rationale in the card only when it's a decision a future reader
  must be able to revisit.
