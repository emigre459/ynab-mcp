---
description: Before drafting any spec/code that names a third-party library's API (imports, signatures, decorators, integration shape), fetch current docs — don't rely on training data.
alwaysApply: true
---

# Fetch library docs before drafting integration code

Before writing any spec section or code that names a specific function, import
path, decorator, callback signature, or framework-integration pattern from a
third-party library, **fetch the current docs first** — even when you think you
know it. Training data lags; names and signatures change.

**Why:** Confidently drafting from memory produces wrong import paths
(e.g. guessing `some_lib.callback.Handler` when the real path is
`some_lib.integrations.Handler`), invented constructor args, and missed setup steps.

**How to apply**
1. Use Context7 (`resolve-library-id` + `query-docs`) or `WebFetch` against the
   official docs. (This complements the global Context7 rule in
   `~/.claude/rules/context7.md`.)
2. Verify imports, signatures, and recommended setup against what you're about to
   write.
3. Where docs leave a question open, flag the uncertainty explicitly rather than
   asserting an unverified shape; note which facts came from docs vs. inference.

Applies to spec drafting and implementation alike — never write `from foo import
Bar` on the assumption that `foo` probably exports `Bar`.
