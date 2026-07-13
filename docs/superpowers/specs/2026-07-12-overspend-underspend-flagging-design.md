# Overspend/Underspend Flagging & Trend Analysis — Design

- **Issue:** [#13](https://github.com/emigre459/ynab-mcp/issues/13) — Overspend/underspend flagging & long-term trend analysis
- **Parent epic:** [#10](https://github.com/emigre459/ynab-mcp/issues/10) — AI-driven budget coaching & categorization for parents' YNAB budget
- **Date:** 2026-07-12

## Why

This is the founding ask behind epic #10: flag categories that are over/under budget in a
given month, and detect multi-month patterns — a category whose budget keeps getting
raised while it still overspends, or a category that's persistently underspent and worth
reallocating — so the user can course-correct their parents' budget. Read-only; budget
write tools are issue #12's job.

## Architecture

Both tools live in one new module, `src/ynab_mcp/tools/spend_analysis.py` — a single
"tool group" per the `AGENTS.md` `tools/` convention (one module per tool group; the two
tools here are closely related and share a fetch helper, unlike e.g. `categories.py` and
`months.py` which are unrelated concerns). The module registers two MCP tools from
`server.py`:

- `flag-category-spend` — single-month over/under-spend flagging.
- `analyze-category-trends` — N-month pattern detection.

Both reuse existing infrastructure: `resolve_budget_id` (client.py), `translate_api_exception`
(errors.py), `parse_month` (imported from `tools/months.py`, not duplicated), and
`ynab.MonthsApi.get_plan_month` (the SDK call `months.py`'s `get_month_info` already
wraps). Internally, `spend_analysis.py` calls `MonthsApi.get_plan_month` directly (not
`months.py`'s `get_month_info` tool function) so it works with the raw `ynab.MonthDetail`
object rather than the dict-serialized tool output — no new client/config surface is
needed.

## Shared concepts

**Spend normalization.** YNAB stores `activity` as milliunits, negative for money spent
(e.g. `-42000` = $42.00 spent). Both tools normalize this to a positive `spent` figure
before comparing to `budgeted` (also milliunits, always >= 0 for this purpose). All
milliunit fields in tool output are converted to dollars (float) for readability, matching
the plain-language-output requirement in the issue's acceptance criteria.

**Hidden/deleted categories.** Both tools exclude categories where `hidden=True` or
`deleted=True` — they aren't actionable budget lines a user would want flagged.

**Percent-over/under calculation.** `percent_diff = (spent - budgeted) / budgeted` when
`budgeted > 0`. When `budgeted == 0` and `spent > 0`, the category is always flagged as
overspend (`direction="over"`) with a dedicated reason string, bypassing the percentage
math entirely (division by zero is otherwise undefined, and any spend against a $0 budget
is unambiguous overspend regardless of magnitude). When `budgeted == 0` and `spent == 0`
(category unused this month), the category is not flagged and is treated as "within
threshold" for tool 1, and as neither over- nor under-threshold for tool 2's per-month
pattern classification — there's nothing to compare, so it shouldn't count as evidence
either way.

## Tool 1: `flag-category-spend`

Compares budgeted vs. actual spend for every category in a single month and flags entries
beyond a configurable percentage threshold.

**Parameters:**
- `month: str` — ISO date (`"2024-03-01"`) or `"current"`, same convention as
  `get-month-info`.
- `threshold: float = 0.10` — fraction of budgeted amount; flag if `abs(percent_diff) >=
  threshold`. Must be `>= 0`, else `ToolError`.
- `budget_id: str | None = None` — falls back to `YNAB_DEFAULT_BUDGET_ID`.

**Output:** `list[dict]`, one entry per **flagged** category only (categories within
threshold are omitted — the agent only cares about flags):

```json
{
  "category_id": "...",
  "category_name": "Groceries",
  "budgeted": 300.00,
  "activity": 420.00,
  "direction": "over",
  "percent_diff": 0.40,
  "reason": "Spent $420.00 against a $300.00 budget (40% over)."
}
```

`direction` is `"over"` or `"under"`. The zero-budget case uses a dedicated reason
(`"Spent $X.XX against a $0.00 budget (no budget allocated)."`) with `percent_diff: null`.

## Tool 2: `analyze-category-trends`

Analyzes a trailing window of months per category to detect two patterns: a category
whose budget keeps rising while it still overspends, or a category that's persistently
underspent (worth reallocating).

**Parameters:**
- `months: int = 6` — window size. Must be `>= 1`, else `ToolError`.
- `end_month: str = "current"` — most recent month in the window (same convention as
  `month` above); the window walks backward from here.
- `overspend_threshold: float = 0.10` — per-month over/under threshold (same semantics as
  tool 1's `threshold`), used to classify each individual month as over/under/within
  budget when building the pattern.
- `majority_ratio: float = 0.5` — fraction of the window's months that must show the
  per-month pattern for it to count as a real trend, not a single anomalous month. Must be
  in `(0, 1]`, else `ToolError`.
- `budget_id: str | None = None`.

**Fetch:** calls `MonthsApi.get_plan_month` once per month in the window (N calls — the
YNAB API has no bulk multi-month-with-category-detail endpoint; `get_plan_months` returns
only budget-level totals, not per-category detail). An `ApiException` on any single month
fails the whole request via `translate_api_exception` — no partial/best-effort results.

**Per-category history:** categories are matched by `id` across the fetched months,
walking backward from `end_month`. A category's history length is the count of trailing
months (starting from `end_month`) in which it appears, non-deleted and non-hidden, in
that month's category list. If this is less than `months`, the category is skipped from
pattern detection:

```json
{
  "category_id": "...",
  "category_name": "New Hobby",
  "trend": "insufficient_history",
  "reason": "Insufficient history (2/6 months)."
}
```

**Pattern detection** (evaluated only for categories with full history):

- **`rising_overspend`** — `budgeted` in the most recent month > `budgeted` in the
  earliest month of the window (net increase — tolerates a flat/dip month, catches the
  overall upward trend) **AND** the category was over `overspend_threshold` in
  `>= majority_ratio` of the window's months.
- **`persistent_underspend`** — the category was under `overspend_threshold` in
  `>= majority_ratio` of the window's months. No budget-direction requirement; persistent
  underspend alone is the signal worth surfacing for reallocation.
- Categories matching neither pattern are omitted from output (same "only flag actionable
  entries" principle as tool 1).

**Output** (for flagged categories): same shape as tool 1's per-category fields, plus:

```json
{
  "category_id": "...",
  "category_name": "Car Repairs",
  "budgeted": 350.00,
  "trend": "rising_overspend",
  "months_over_threshold": 4,
  "months_in_window": 6,
  "reason": "Budget raised from $200.00 to $350.00 over 6 months but overspent in 4/6 months."
}
```

`budgeted` in trend output is the most recent month's value. `months_over_threshold` /
`months_under_threshold` (whichever applies to the detected trend) plus `months_in_window`
give the agent the majority-rule evidence directly, so the plain-language `reason` isn't
the only place the math is visible.

## Error handling

- Invalid `month` / `end_month` → `ToolError` via the shared `parse_month` (imported from
  `tools/months.py`).
- `threshold` / `overspend_threshold < 0`, `majority_ratio` outside `(0, 1]`, or
  `months < 1` → `ToolError` with a specific message, checked before any API calls.
- `ynab.ApiException` on any fetch → `translate_api_exception`, consistent with every
  other tool in the repo.

## Testing plan

New `tests/test_tools_spend_analysis.py`, mirroring `test_tools_months.py`'s style (mocked
`ynab.MonthsApi`, `SimpleNamespace` / mocked `ynab.Category` fixtures, `pytest_mock`).

**`flag-category-spend`:**
- Category over threshold → flagged, `direction="over"`.
- Category under threshold → flagged, `direction="under"`.
- Category within threshold → not flagged (absent from output).
- Zero-budgeted category with activity → always flagged, `percent_diff=None`.
- Hidden category → excluded even if over threshold.
- Invalid `month` → `ToolError`.
- Negative `threshold` → `ToolError`.
- `ApiException` from the SDK → `ToolError`.

**`analyze-category-trends`:**
- Rising budget + majority-of-months overspend → `rising_overspend`.
- Majority-of-months underspend → `persistent_underspend`.
- Single anomalous month (one over-threshold month out of N, below majority) → not
  flagged.
- Category with fewer trailing months than the window → `insufficient_history`, correct
  `X/N` count.
- Hidden category → excluded from trend detection.
- `months < 1` → `ToolError`.
- `majority_ratio` outside `(0, 1]` → `ToolError`.
- `ApiException` on any of the N fetched months → `ToolError`.

## Out of scope

- Any write/budget-adjustment capability (issue #12).
- Statistical outlier detection (mean/std-dev) — majority-of-months rule chosen instead
  for simplicity and explainability (confirmed during brainstorming).
- Multi-budget aggregation — both tools operate on a single `budget_id` per call, same as
  every existing tool.
