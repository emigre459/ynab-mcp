# Transaction categorization & trend-analysis skills — design

Closes #26, amends and closes #27.

## Background

This design formalizes a workflow prototyped live against the real "Rench Budget" in a working session: a best-effort categorization pass over not-yet-approved transactions, and ad hoc anomaly detection (duplicate Lumosity/FuboTV subscriptions, found by pulling per-payee transaction history and cross-checking real-world pricing via web search). Epic #25 already scoped these as two separate, sequenced children — #26 (categorization) then #27 (trend/spend analysis) — because categorization changes the category totals #27 reads. This design keeps that boundary.

## Decisions

1. **#26 writes directly to YNAB** (`bulk-manage-transactions`, `category_id` only, `approved` never touched) rather than the propose-to-CSV pattern used during the prototype session. The CSV step was a one-time trust-building exercise, not the intended steady state.
2. **Two separate skills**, not one combined skill, matching the epic's existing sequencing plan and this repo's one-card-per-skill convention.
3. **Subscription-cadence detection** (the Lumosity/FuboTV technique) is folded into #27's scope, as an addition to its "Lingering Questions" acceptance criterion, rather than becoming a new issue. #27's GitHub body will be amended accordingly.
4. **Only hard-evidence categorizations auto-write.** Two evidence tiers:
   - **Tier 1 (auto-write):** a matched Amazon order with a real order number and parseable item text (categorized by the agent's own reading of the item description — not keyword/regex rules, see "Amazon item categorization" below), OR a `find-payee-transactions` history with ≥3 prior transactions and a `most_common_category` that isn't itself "Uncategorized."
   - **Tier 2/3 (needs review, never written):** general merchant knowledge with no YNAB-side evidence, ambiguous Amazon ties, unmatched transactions, or genuinely no data (e.g. paper checks with no payee/memo).
   This bar exists because the prototype session found real false positives in naive keyword matching (see below) — hard evidence only, until the approach has a track record.
5. **Implementation is two agent skills** under `.agents/skills/`, not new Python/MCP tool modules. The category-matching step is fundamentally a text-understanding judgment call (deciding what a purchase actually was, avoiding marketing-copy false positives), which fits an LLM-driven skill better than hard-coded rules — see "Approaches considered."

## Approaches considered

- **Agent skills calling existing tools (chosen).** No new Python code. Matches this repo's existing skill layer (`build-from-issue`, `plan-issues`) for judgment-heavy, multi-tool orchestration work. Deterministic data-fetching/merging already lives in Python (`amazon_matching.py`); deciding *what a purchase was* does not need to.
- **New composite MCP tools (Python, TDD).** Matches every other epic-#10/#25 child so far, fully testable, callable without an LLM in the loop. Rejected because the category-matching step would have to hard-code text-matching rules, re-encoding the prototype session's real bugs as "real" code (see below) instead of leveraging language understanding.

## Amazon item categorization — avoid keyword-rule false positives

During the prototype session, a first-pass regex/keyword categorizer produced two confirmed false positives:

- A storage-bag + Tide PODS order was tagged "Medical" because its marketing copy mentioned "First Aid Kits" as a use-case, not because it was a medical item.
- A Google Pixel Watch (smartwatch) order was tagged "Home Supplies" because its description mentioned "battery life."

Both were rule-ordering/keyword-collision bugs inherent to regex matching on free-text marketing copy. The skill instructions must tell the agent to **read and reason about the item description directly** against the real YNAB category list (`list-categories`), not apply keyword rules — this is the reason Approach A (agent skill) was chosen over Approach B (hard-coded Python matching). For multi-item orders, categorize by the primary/first item.

## Payee data-quality checks

`payee_name` can be silently merged across unrelated real merchants by YNAB's payee-matching (confirmed in the prototype: a doctor's office charge and a credit-card payment were both merged into unrelated Amazon-ish payees). Both skills must key off `import_payee_name_original` (the raw bank descriptor) rather than trusting `payee_name` alone, and `categorize-unapproved-transactions` should surface any such mismatches it finds as an explicit output, separate from ordinary categorization.

## Skill: `categorize-unapproved-transactions` (#26)

**Location:** `.agents/skills/categorize-unapproved-transactions/SKILL.md`

**Trigger:** `/categorize-unapproved-transactions`, plus natural-language ("categorize the unapproved transactions").

**Inputs:** `budget_id` (ask if ambiguous/unconfigured).

**Flow:**
1. Resolve `budget_id`, then run `scripts/check_no_approvals.py snapshot` (see below) before any other reads/writes begin.
2. Pull unapproved, non-deleted transactions via `list-transactions`, and the category list via `list-categories`. Use jq-based extraction for large results (per the tools' own guidance) rather than reading raw JSON directly.
3. For each transaction, normalize payee identity from `import_payee_name_original`, not `payee_name`.
4. Call `find-amazon-transactions` once for the relevant date range (not per-transaction). Call `find-payee-transactions` sequentially, one at a time — avoid unnecessary parallel fan-out even though #17's retry/backoff (merged) now makes the underlying calls resilient to transient 429s, since avoiding the rate-limit hit in the first place is still cheaper than retrying through it.
5. Classify each transaction into the evidence tiers above. Separately identify internal transfers (via `transfer_account_id`, or the same-amount/near-date pattern across two tracked accounts observed in the prototype) — no category applies, never written.
6. Issue one batched `bulk-manage-transactions` call with `update` operations for every tier-1 transaction, setting `category_id` (and a `memo` recording the evidence, e.g. "Auto-categorized: Amazon order #113-xxx — Hefty Storage Bags," since existing memos were confirmed null in the prototype data and this leaves an audit trail visible inside YNAB itself). `approved` is never included in any operation.
7. Run `scripts/check_no_approvals.py verify <snapshot-file>` and fold its result into the summary.
8. Output a structured summary — counts written vs. needs-review (grouped by category and by reason), the needs-review list itself, any payee data-quality mismatches found, and the approval-safety check result — plus a human-readable chat rendering of the same.

**Error handling:** if `bulk-manage-transactions` partially fails, report exactly which transaction IDs succeeded and which didn't, with the real error — never claim full success on a partial write.

**Deterministic approval-safety invariant.** The skill must never rely on its own prose instructions as the only guarantee it didn't approve anything — a bundled script, not skill text, does the actual verification, so the guarantee doesn't depend on the agent behaving as instructed:

- `scripts/check_no_approvals.py` (bundled with this skill, run via `Bash`, independent of any MCP tool call — it talks to the YNAB API directly via the `ynab` Python client and the same `YNAB_PAT`/`.env` the server uses) has two subcommands: `snapshot` (writes the full set of unapproved, non-deleted transaction IDs for the budget to a temp file, plus the count) and `verify <snapshot-file>` (re-fetches, and asserts every ID in the snapshot is still present in the current unapproved set).
- The skill runs `snapshot` as step 1, before any reads/writes begin, and `verify` at step 7, immediately after the `bulk-manage-transactions` call and before assembling the final summary.
- `verify` checks **set containment**, not just `n_start <= n_end` — a bare count comparison can mask the exact bug we're guarding against (some transactions wrongly approved while an unrelated bank sync happens to add new unapproved ones in the same window, netting a count that still looks fine). Containment catches that; it's the same technique used to conclusively rule out an accidental approval during this project's own prototype session, just automated instead of ad hoc.
- On violation, the script exits non-zero and prints the exact offending transaction IDs. The skill treats this as a hard failure — reports it prominently, does not continue or paper over it.

## Skill: `analyze-budget-trends` (#27, amended)

**Location:** `.agents/skills/analyze-budget-trends/SKILL.md`

**Trigger:** `/analyze-budget-trends`, plus natural-language ("run the monthly trend analysis").

**Inputs:** `budget_id`, target month (defaults to current; must accept an arbitrary month, since the eventual monthly-review orchestrator triggers on the 1st for the just-closed month).

**Flow:**
1. Resolve `budget_id` and target month.
2. Call `flag-category-spend` and `analyze-category-trends` for the target month; bucket into budget successes vs. budget failures (recurring overspend despite budget increases).
3. For each failure, propose (never write) a next-month budgeted-amount change with a one-line rationale.
4. **Subscription-cadence detection:** for payees that look recurring, pull full transaction history (`find-payee-transactions` / `list-transactions` filtered by `payee_id`), compute gaps between charge dates, and check whether the sequence decomposes into overlapping cycles rather than one clean period. Cross-check plausibility of the amounts against real-world vendor pricing via `WebSearch` before flagging anything (the Lumosity/FuboTV session is the worked example the skill text should reference).
5. Assemble the "Lingering Questions" list — anomalous one-off transactions, still-uncategorized items handed off from #26's needs-review output, subscription-cadence anomalies, and unexplained trends — each with at least one plausible explanation attached, never a bare "this looks weird."
6. Output one structured report (successes, failures, suggested changes, lingering questions) plus a chat-readable rendering.

**Dependency:** assumes `categorize-unapproved-transactions` already ran for the target month, since category totals need to be settled first. This is recorded here as a design assumption; actual sequencing enforcement belongs to the not-yet-built monthly-report orchestrator (epic #25, child 3).

## Shared conventions

- **Tool scoping (`allowed-tools`):** `categorize-unapproved-transactions` gets `list-transactions`, `list-categories`, `find-payee-transactions`, `find-amazon-transactions`, `bulk-manage-transactions`, `AskUserQuestion`, `Bash`. `analyze-budget-trends` gets `list-transactions`, `flag-category-spend`, `analyze-category-trends`, `find-payee-transactions`, `WebSearch`, `AskUserQuestion`, `Bash`. Neither gets `manage-scheduled-transaction`, `manage-payees`, or anything that could approve a transaction.
- **No git worktree at runtime.** Both skills operate live against YNAB via MCP tools and touch no repo files when invoked. (Building the skill files themselves, as with any repo-tracked change, does happen in a worktree — this session is in one.)
- **Testing:** no unit-test suite — these are prompt-workflow skills, not Python. Validation is live, against the real budget, matching `build-from-issue`/`plan-issues` today. Deliberate trade-off, not an oversight.
- **File layout:** `analyze-budget-trends` is `SKILL.md` only. `categorize-unapproved-transactions` additionally bundles `scripts/check_no_approvals.py` (see "Deterministic approval-safety invariant" above) — referenced skill-root-relatively per `.agents/rules/shared/harness-agnostic-skills.md`. This is the only skill of the two with write access, so it's the only one that needs the check.

## Out of scope

- The monthly-report orchestrator (deck-building, Cowork scheduling, email delivery) — epic #25 child 3, not yet an issue.
- Any change to `YNAB_READ_ONLY` gating or the underlying MCP tools themselves.
- Retrying #26's needs-review items automatically — they stay for manual review until a human (or a future, more evidenced pass) resolves them.

## Implementation note

Skill files will be authored using `anthropic-skills:skill-creator` during the implementation phase, per explicit request.
