---
name: clean-up-kanban
description: Kanban hygiene + board-review playbook for the repo's GitHub Project board. Use when running a full or partial board review ("clean up the kanban", "review our issues", "is the board stale?"), when adopting orphaned issues into epics, when writing or refreshing an EPIC body, or when plan-issues / build-from-issue delegate here for the epic-body template and staleness rules. Encodes the board conventions (epic template with product outcome + lifecycle stage, three-bucket review, close-don't-delete, amendment blocks, Stage field) — originated in a 2026-07-07 full-board review.
---

# Clean Up Kanban

## Overview

The board decays in four ways, and this skill is the countermeasure for each:

| Decay mode | Countermeasure (section) |
|---|---|
| Cards outlive the code they describe (premises deleted, blockers closed, architecture moved) | Three-bucket review, grounded in code (§2) |
| Orphans accumulate — hand-filed cards bypass the planning skills and never get a parent | Orphan-adoption sweep (§4) |
| Duplicate efforts sprout because nobody searched before filing | Duplicate hunt (§5) |
| Epic bodies rot into bare child lists that mislead `/build-from-issue` | Epic-body template (§1) |

**Announce at start:** "Using clean-up-kanban to <review the board | adopt orphans | refresh epic #N>."

This skill READS broadly and WRITES only with per-item user approval (same approval discipline as plan-issues Phase 4). It never deletes — closure-with-comment only.

**Origin case study (2026-07-07):** 35 orphans existed; zero carried the `/plan-issues` footer — orphaning is caused by hand-filed cards, not by skill failure. Hence §4's standing sweep rather than a one-time fix.

## §1 The epic-body template (the load-bearing artifact)

Every epic body MUST tell a story a `/build-from-issue` agent can navigate from cold. Required sections:

```markdown
## Product outcome
What customer-visible value this epic creates or improves, in 1-3 sentences.
**Lifecycle stage: <0 — POC | 1 — Hardening | 2 — Later>** (+ per-child
exceptions if mixed). Note parallelism with other in-flight epics and whether
this epic is TEMPORALLY DRAINABLE (default) or a standing index (rare —
DevEx-type containers; say so explicitly).

## Foundation (merged — build on, don't re-litigate)
The shipped PRs/issues whose decisions children must not reopen.

## The story — children, roles, and execution order
One line per child: its role in the arc, its blockers, and whether it runs
sequentially or in parallel with siblings. This is a NARRATIVE, not a
checklist — say WHY these cards are siblings.

## End-state
What "this epic is drained" observably looks like.
```

Lifecycle-stage definitions (Dave, 2026-07-07):
- **0 — POC / early build**: first customers realize value FAST; intermediate/dirty code acceptable.
- **1 — Hardening / validation**: bugfixing, tech-debt paydown, pushing the proven POC toward GA.
- **2 — Later**: accuracy improvements and nice-to-haves; deliberately deferred until traction.

Stage also lives on the **Project's `Stage` single-select field** (sortable in board views; create it once per Project: settings → New field → single select with the three stage options) — set it on the epic (and optionally children) whenever you create or re-stage one. The Project's `Priority` field expresses urgency, which is a DIFFERENT axis (a hardening-stage bug can be Urgent).

**Whenever you nest a card under an epic, re-read the epic body** — if the new child has no place in its story, either amend the story or question the nesting (plan-issues' amend-vs-wrong-home fork).

## §2 The three-bucket board review

For a full review (quarterly, or on request), classify every open issue:

1. **WELL** — approach still intelligent; keep (possibly amend/re-parent).
2. **AMBIGUOUS** — may be fine, may need work; MUST name the resolver (a decision, a measurement, or an owner) — never leave it as vibes.
3. **WRONG** — premise contradicted by shipped code or a decided direction; close-with-comment or wholesale-rescope.

Non-negotiable method rules:

- **Ground every verdict in the repo, not in the card.** Read AGENTS.md constraints, grep for the card's named modules/tests, check `git log` / closed issues for what already landed. A card citing `BmsSnapshot`, `analysis.py`, deepagents-as-runtime, or other deleted artifacts is prima facie stale.
- **Scale with subagents.** For >30 issues, fan out one analysis agent per thematic cluster (~15-30 issues each), each instructed to verify claims against code and return per-issue: bucket, status (current/stale/duplicate-of/subsumed-by), action (keep/amend/merge/close/re-parent), one-line rationale, plus cluster-level epic-structure verdict + critical path. Dump all issue bodies to one JSON first (`gh api --paginate .../issues?state=open`) so agents don't re-fetch.
- **Check phantom blockers**: any open card whose declared blocker is CLOSED gets flagged — these silently idle high-value work.
- **Produce-before-consume check**: for each data-producing investment, name its consumer; extraction/capture work with no consuming card is a red flag either way (missing consumer card, or over-investment).
- **Sharpen weakly-phrased cards**: any card without Why + Acceptance bullets (hand-filed ones usually) gets them added during the amendment pass.

## §3 Writing changes back (the amendment discipline)

- **Amendments are dated, append-only blocks**: `## Amendment — YYYY-MM-DD <context>` appended to the body — never silently rewrite history. Retitles are allowed alongside.
- **Closures pair a comment with the close**: the comment names WHY (superseded-by-shipped-X / merged-into-#N / premise-deleted) and links every successor. NEVER `gh issue delete`.
- **Merges**: the survivor's amendment absorbs the closed card's unique content; the closed card's comment points forward.
- **Re-parents**: sub-issues have ONE parent — query the actual parent first (`gh api graphql ... issue(number:N){parent{number}}`), un-nest (`DELETE .../issues/{old}/sub_issue -F sub_issue_id=<db-id>`), then nest. Verify by readback.
- **Blocked-by edges are GH-native** (REST dependencies endpoint, integer DB ids via `-F`, readback verify) — body text alone is invisible to the dependency graph.
- **Batch execution**: for >10 write operations, author a manifest (epics/cards/closures/amendments JSON) + a small idempotent executor with a state file, get user approval on the manifest, then run staged (`epics → cards → reparent → wire → amend → close-cards → close-epics`). This makes the work reviewable before it happens and resumable after any failure.
- **Verify, don't flag.** Never end a materialization by *telling the user* something might be inconsistent ("verify X nested correctly") when one API call would answer it — check it yourself and fix it in-session. Specifically: every child named in an epic body's story MUST appear in that epic's `sub_issues` readback before you report done; a narrative-only child is a silent orphan (this exact miss happened in the origin case study: five cards written into an epic's story but never nested).
- **Epic-level ordering is wired, not just written.** When epic bodies declare a drain order, express it with GH-native blocked-by edges between the EPICS themselves (semantics: scheduling order, not strict technical dependency — say so in the epic bodies). Parallel epics get no edge.

## §4 Orphan-adoption sweep

Orphans happen because cards get hand-filed outside plan-issues (verified in the origin case study: 0/35 orphans came from the skill). Standing countermeasure, runnable alone:

1. List open issues; compute the unparented set (not a sub-issue of any epic — check via each epic's `sub_issues` endpoint or the GraphQL `parent` field).
2. For each orphan: propose the best-fit epic from the live inventory; if none fits, propose the epic it WOULD seed — **a card may name a not-yet-created epic in its body** ("Would-be epic: <title>") rather than stand truly parentless; create the epic only when it would have ≥2 members.
3. Add missing labels and Why/Acceptance bullets while you're in there (§2 sharpening).
4. Per-item user approval, then materialize per §3.

## §5 Duplicate hunt (run BEFORE creating anything)

When a user describes new work (plan-issues) or a branch implies work (build-from-issue):

1. Search open issues by keyword AND by the affected modules' paths/names.
2. Present overlaps with a recommendation each: use as-is / amend-to-fit / genuinely new.
3. Prefer amending an existing card over creating a sibling; if the existing card is stale beyond amending, the new card supersedes it and the old one closes-with-comment IN THE SAME SESSION — never leave both open.
4. While there: any card the search surfaced that no longer reflects product state gets flagged for closure even if unrelated to the current ask.

## §6 Cross-repo + convention guardrails

- **Cross-tracker routing**: when the repo defines routing rules (e.g. server-side work belongs on another team's Jira via a twin-card pattern), classify each card before filing — never file work on the wrong tracker.
- **Cross-repo routing**: when the org splits surfaces across repos (backend / frontend / eval tooling), file each card in the OWNING repo, attached to the shared GH Project for portfolio visibility; the current repo keeps the backend/contract halves.
- Epics are labeled `EPIC` (uppercase) + `[EPIC] ` title prefix — both, always.
- New/amended core dev skills (this one included) in downstream repos → suggest an upstream PR to the shared template repo at finalization so the canonical copy stays in sync.

## §7 Ready-set computation, in-flight detection, and assignment signals

The shared logic behind build-from-issue's Step 0 (propose next, session start) and Step 11b (momentum hook, PR created) — one computation, two moments. Keep the two call sites consistent with THIS section.

**Ready set.** A card is READY iff: (a) open, (b) every GH-native blocker is closed, (c) its parent epic's blockers are drained OR the epic is an explicitly-parallel track (no edge between the epics). Compute from the dependencies API, never from body prose.

**In-flight classifier** (strongest signal wins; ground every verdict in the evidence):
1. **Open PR referencing the issue** → definitely in-flight. Never propose; name the PR.
2. **Remote branch matching the issue** (leading `{number}-` in the branch name, or `gh issue develop --list` link) **with commits ahead of main and recent activity (~7 days)** → probably in-flight. Don't propose; say who pushed last.
3. **Stale branch** (matches the issue, but no PR, no recent commits) → "started-and-stalled": surface as a RESUME candidate, distinct from fresh picks.
4. **Project `Status` = In progress** → treat as in-flight when populated (weakest signal; often unmaintained).

This classifier is why the push-every-commit rule exists: local-only branches are invisible here and cause duplicate work.

**Assignment signals** (GitHub assignees carry ownership):
- **Issue assignee = claimed.** build-from-issue assigns the invoking user (`gh api user --jq .login`) when branch work begins.
- **Epic assignee = track owner.** The FIRST user to start work on any child claims the unassigned epic (assumption: whoever worked the first issue likely works the rest). No epic with in-flight children may be unassigned.
- **Ranking:** cards/epics assigned to the invoking user rank FIRST; unassigned rank second; assigned-to-someone-else are EXCLUDED from proposals (listed with the owner's name so the exclusion is auditable).
- **Conflict handling (two tiers, matching build-from-issue Step 1g):** an ISSUE assigned to someone else is a hard STOP — surface it and proceed only on explicit resolution or a different pick. An EPIC assigned to someone else is a soft FLAG — name the track owner in one sentence and proceed unless the user redirects (cross-track help on individual cards is normal). Never silently reassign either.

**Ordering within the ready set:** (1) assigned-to-invoker first, (2) Stage (0 before 1 before 2), (3) Priority (Urgent → Low), (4) epic drain order (the epic-level blocked-by chain), (5) the epic body's prose story order as the final tiebreaker. GH-native edges always outrank prose — prose refines, never overrules.

**Output shape:** recommend a primary pick PER UNBLOCKED EPIC TRACK (parallel tracks are deliberate; a single global answer would keep proposing the other person's lane), plus a parallel-safe set (mutually independent ready cards suitable for concurrently-spun sessions), plus resume candidates. Every exclusion states its evidence.

## Quick reference

| Situation | Action |
|---|---|
| Full board review requested | §2 fan-out → §1 epic audit → §3 manifest + approvals → execute |
| "This epic looks stale" | §1 template check → amend body or restructure children |
| New card about to be created | §5 duplicate hunt first |
| Unparented issues spotted | §4 sweep |
| Card's blocker is closed | Flag + clear the phantom edge; the card may be top of the ready queue |
| >10 writes queued | §3 manifest + staged executor, approval before execution |
