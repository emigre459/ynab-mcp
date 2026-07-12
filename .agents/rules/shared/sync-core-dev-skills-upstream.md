---
description: When YOU edit a core dev/workflow skill under .agents/skills/ in-session (e.g. build-from-issue, plan-issues), suggest opening a PR to the canonical upstream template repo so the change propagates to every repo that inherits the template. Does NOT apply to a repo's own runtime/domain/product skills.
appliesTo: .agents/skills/**
---

# Sync core dev-skill changes to the template repo

The development-time skills under `.agents/skills/` (notably `build-from-issue` and
`plan-issues`, plus their dev-workflow siblings) are **shared best practices**, not
per-repo product code. Their canonical home is the upstream `agentic-ai-powered-repo`
template this project was bootstrapped from — ask the user for its URL/org if it
isn't already known ("store and translate to new repos our best practices for
AI-powered development"). Every repo that inherits the template vendors a copy (commonly surfaced at
`.claude/skills/` and/or `.cursor/` per platform). A change made in only one place
drifts; the template and its inheritors must be kept in lockstep.

## When this fires (the trigger is directional)

- **FIRE** when **you (the agent) edited a core dev/workflow skill under
  `.agents/skills/`** (or its platform mirror `.claude/skills/` / `.cursor/…`)
  **during this session** — `build-from-issue`, `plan-issues`, or a sibling
  dev-tooling skill (`pr-check`, `resolve-pr-concerns`, `review-skill`, `run-tests`, …).
- **DO NOT FIRE** for edits to a repo's own **runtime / domain / product skills**
  (an inheriting repo's ECM skills, orchestrators, etc.). Those live in that repo, not here.
- **DO NOT FIRE** when the skill changed from **outside** the session (e.g. arrived
  via a template sync / `git pull`) — that direction is already covered.

## What to do when it fires

- **In an inheriting repo:** as part of finalizing that repo's PR, **suggest** opening
  a companion PR **back to the upstream template repo** so the canonical copy —
  and thus every other inheriting repo — picks up the change.
- **In this template repo:** land the change here; inheriting repos pick it up on
  their next template sync.

Either way, **name the skill file(s) you changed and offer to open the sync PR**.

This is a **suggest, not an auto-do**:

- Don't silently skip it — surfacing the sync reminder is mandatory.
- Don't blind-copy / force-push across repos without the user's go-ahead. The
  template is platform-agnostic; an inheriting repo's copy may carry repo-specific
  wording, and the template may carry generalized / Cursor+Claude-portable phrasing.
  The sync usually needs a **hand-reconciled diff**, not a verbatim copy.

The syncing direction and exact diff are a human call; the reminder to sync is not.
