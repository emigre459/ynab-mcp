# Payee/Transaction Pattern Lookup Tool — Design

**Issue:** [#14](https://github.com/emigre459/ynab-mcp/issues/14) — Payee/transaction pattern lookup tool
**Parent epic:** [#10](https://github.com/emigre459/ynab-mcp/issues/10) — AI-driven budget coaching & categorization for parents' YNAB budget

## Why

Quick questions like "what transaction keeps showing up under payee X" are hard to answer by scrolling YNAB manually, especially for a payee with inconsistent naming (e.g. "AMZN Mktp" vs "Amazon.com" both meaning Amazon). This tool answers that question directly: given a payee name or substring, it returns the matching payees' transaction patterns — frequency, typical amount, most common category — and a best-guess recurring-charge summary when one is obvious.

## Architecture & data flow

A new module `src/ynab_mcp/tools/payee_patterns.py`, following the existing `tools/*.py` pattern established in the server-foundation card: a plain, independently-testable function plus a thin `register(mcp, client, settings)` function that wraps it as an `@mcp.tool`.

The tool is purely a read-and-aggregate layer over already-registered tools — it does not add any new YNAB API surface. It imports and calls `list_payees` and `list_transactions` directly (`from ynab_mcp.tools.payees import list_payees`, `from ynab_mcp.tools.transactions import list_transactions`) — the same cross-tool-module function-import pattern `lookup.py` already establishes (`from ynab_mcp.tools.months import parse_month`):

1. Call `list_payees` to fetch every payee in the budget.
2. Match payee names against the caller's `payee_query` (matching strategy below).
3. For each matched payee, call `list_transactions` with `payee_id` set, to fetch that payee's transactions.
4. Compute per-payee-group statistics and assemble the response.

This keeps all YNAB API-calling logic centralized in the existing `payees.py`/`transactions.py` modules; `payee_patterns.py` only orchestrates and aggregates.

## Matching strategy

For each payee name in the budget, compared case-insensitively against `payee_query`:

1. **Exact match** — the payee name equals the query (case-insensitive). `match_type = "exact"`.
2. **Substring match** — the query is a substring of the payee name, or vice versa. `match_type = "substring"`.
3. **Fuzzy fallback** — for payees that don't match by 1 or 2, compute a `difflib.SequenceMatcher(None, query.lower(), payee_name.lower()).ratio()`. If the ratio is `>= fuzzy_threshold` (default `0.6`), include it with `match_type = "fuzzy"` and the score attached.

Substring is checked before fuzzy scoring so obviously-contained matches (e.g. "amazon" in "Amazon.com") are never at the mercy of a similarity-ratio cutoff; fuzzy scoring only kicks in for names that don't literally contain the query, catching abbreviations like "AMZN Mktp US" for a search on "amazon".

If no payee matches by any of the three, the tool returns an empty list — not an error. An empty result is itself a meaningful answer ("no pattern found for that query").

## Grouping

Each matched **payee name** is its own group with its own stats — not a single pooled summary across all matches. YNAB tracks "Amazon.com" and "AMZN Mktp US" as distinct payee records even though a human recognizes them as the same vendor; collapsing them into one pooled group would hide that distinction and make the "most common category" stat meaningless if the two payees are categorized differently. The caller sees each variant's pattern separately and can connect the dots.

## Tool interface

```python
def find_payee_transactions(
    client: ynab.ApiClient,
    budget_id: str,
    payee_query: str,
    fuzzy_threshold: float = 0.6,
) -> list[PayeeGroupSummary]:
    ...
```

Registered as the MCP tool `find-payee-transactions`:

```python
def find_payee_transactions_tool(
    payee_query: str,
    budget_id: str | None = None,
) -> list[dict[str, object]]:
    ...
```

`fuzzy_threshold` is a plain-function parameter (useful for tests and future tuning) but is **not** exposed as an MCP tool parameter — the issue doesn't call for caller-configurable fuzziness, and exposing it would be premature surface area.

### `PayeeGroupSummary` shape

A frozen `dataclass` — the codebase's only precedent for a local (non-SDK) structured type is `Settings` in `config.py`, itself a frozen dataclass, and `PayeeGroupSummary` is analogously a locally-computed aggregate rather than an SDK model. The `register()`-wrapped tool function converts it to a plain dict for the MCP response (`dataclasses.asdict`), matching how every other tool converts its SDK models via `.model_dump(mode="json")` at the same boundary. Fields:

| Field | Type | Description |
|---|---|---|
| `payee_id` | `str` | The matched YNAB payee id. |
| `payee_name` | `str` | The matched YNAB payee name. |
| `match_type` | `Literal["exact", "substring", "fuzzy"]` | How this payee matched the query. |
| `match_score` | `float \| None` | The `difflib` ratio, only set when `match_type == "fuzzy"`. |
| `transaction_count` | `int` | Number of transactions for this payee. |
| `typical_amount` | `int` | Median transaction amount, in YNAB milliunits (matches SDK convention). |
| `amount_range` | `{"min": int, "max": int}` | Min/max transaction amount, in milliunits. |
| `most_common_category` | `str \| None` | Mode of `category_name` across the group's transactions; `None` if none are categorized. |
| `recurring_guess` | `str \| None` | A human-readable guess (e.g. `"Looks like a recurring charge (~$14.99, seen 6 times)"`) when the recurring heuristic fires; otherwise `None`. |

Response contains **stats only** — no raw transaction list nested in the result. The issue's use case is quick pattern Q&A, not transaction browsing; `list-transactions` (filtered by the returned `payee_id`) already covers drill-down if the caller wants the underlying records.

## Recurring-charge heuristic

A payee group is flagged as a probable recurring charge when **both**:

1. `transaction_count >= 3`, and
2. Amounts are consistent — every transaction's amount falls within a tolerance band of the median (e.g. within ±10%, or an absolute milliunit floor for very small typical amounts to avoid false negatives on cheap recurring charges).

Interval regularity (are the dates ~monthly apart?) is explicitly **out of scope** for this pass — count + amount consistency alone catches the common cases (subscriptions, recurring bills) without date-gap analysis complexity. This can be revisited in a future card if the heuristic proves too noisy in practice.

When the heuristic fires, `recurring_guess` is populated with a natural-language summary including the typical amount and how many times it was seen. When it doesn't, `recurring_guess` is `None` — the caller still has the raw stats to judge for themselves.

## Error handling

- Empty or whitespace-only `payee_query` raises `fastmcp.exceptions.ToolError`, mirroring `list-transactions`' validation style (e.g. its multiple-entity-filter check) — this is a caller-input error, not an API error.
- `budget_id` resolution reuses `resolve_budget_id` (same default-budget-fallback behavior as every other tool).
- Errors from the underlying `list_payees`/`list_transactions` calls (i.e. `ynab.ApiException`) propagate as-is — those functions already translate them to `ToolError` via `translate_api_exception`. `payee_patterns.py` does not catch or re-wrap them.

## Testing

Unit tests in `tests/test_tools_payee_patterns.py`, mocking the imported `list_payees`/`list_transactions` functions directly at their point of use in the new module (`mocker.patch("ynab_mcp.tools.payee_patterns.list_payees")`, `mocker.patch("ynab_mcp.tools.payee_patterns.list_transactions")`) rather than the underlying SDK API classes — `payee_patterns.py`'s own tests only need to verify its matching/aggregation logic, not re-verify `list_payees`/`list_transactions`' own SDK-calling behavior (already covered by `test_tools_payees.py`/`test_tools_transactions.py`). Cases:

- **Exact match** — query equals a payee name case-insensitively; result has one group with `match_type == "exact"`.
- **Substring match** — query is a substring of a payee name; `match_type == "substring"`.
- **Fuzzy match** — a payee name that doesn't contain the query but scores above `fuzzy_threshold` (e.g. "AMZN Mktp US" vs "amazon"); `match_type == "fuzzy"` with `match_score` set.
- **No match** — no payee scores above threshold or contains the substring; result is `[]`.
- **Stats correctness** — given a fixed set of transactions for a matched payee, `transaction_count`, `typical_amount` (median), `amount_range`, and `most_common_category` compute correctly.
- **Recurring guess fires** — ≥3 transactions with consistent amounts produces a non-`None` `recurring_guess`.
- **Recurring guess does not fire** — fewer than 3 transactions, or inconsistent amounts, leaves `recurring_guess` as `None`.
- **Empty query validation** — empty/whitespace `payee_query` raises `ToolError`.

## Out of scope (deferred)

- Caller-configurable `fuzzy_threshold` via the MCP tool surface.
- Date-range filtering on the lookup (the existing `list-transactions` tool already supports this for drill-down).
- Interval-regularity (date-gap) analysis for the recurring heuristic.
- Cross-payee-name pooling (treating "Amazon.com" and "AMZN Mktp US" as one merged group) — deferred to whatever future payee-merge/dedup tooling the write-tools epic child introduces, if any.
