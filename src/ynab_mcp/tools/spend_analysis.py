"""Budget vs. actual spend analysis: flag-category-spend, analyze-category-trends."""

from datetime import date

import ynab
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from ynab_mcp.client import call_with_retry, resolve_budget_id
from ynab_mcp.config import Settings
from ynab_mcp.errors import translate_api_exception
from ynab_mcp.tools.months import parse_month


def _to_dollars(milliunits: int) -> float:
    """Convert a YNAB milliunit amount to dollars, rounded to 2 decimals.

    Parameters
    ----------
    milliunits : int
        A YNAB amount in milliunits (1/1000 of a currency unit).

    Returns
    -------
    float
        The amount in dollars, rounded to 2 decimal places.
    """
    return round(milliunits / 1000, 2)


def _spent_milli(category: ynab.Category) -> int:
    """Return a category's spend for the month, in milliunits.

    YNAB stores ``activity`` as negative-for-spend; this negates it so
    positive values mean money spent (and negative values mean a net
    refund exceeding spend).

    Parameters
    ----------
    category : ynab.Category
        A category as returned for a single month.

    Returns
    -------
    int
        Milliunits spent (positive = spent, negative = net refund).
    """
    return -category.activity


def _percent_diff(budgeted: int, spent: int) -> float | None:
    """Compute the fractional difference between spend and budget.

    Parameters
    ----------
    budgeted : int
        Budgeted amount in milliunits.
    spent : int
        Amount spent in milliunits (see ``_spent_milli``).

    Returns
    -------
    float | None
        ``(spent - budgeted) / budgeted``, or ``None`` if ``budgeted`` is 0
        (the ratio is undefined).
    """
    if budgeted == 0:
        return None
    return (spent - budgeted) / budgeted


def _direction(budgeted: int, spent: int, threshold: float) -> str | None:
    """Classify a single category-month as over, under, or within threshold.

    A zero-budgeted category with nonzero spend is always "over" (any
    spend against no budget is unambiguous overspend). A zero-budgeted
    category with zero spend has nothing to compare and is not flagged.

    Parameters
    ----------
    budgeted : int
        Budgeted amount in milliunits.
    spent : int
        Amount spent in milliunits (see ``_spent_milli``).
    threshold : float
        Fraction of the budgeted amount beyond which spend is flagged.

    Returns
    -------
    str | None
        ``"over"``, ``"under"``, or ``None`` if within threshold (or a
        zero-budget, zero-spend category with nothing to compare).
    """
    if budgeted == 0:
        return "over" if spent > 0 else None
    percent_diff = (spent - budgeted) / budgeted
    if percent_diff == 0 or abs(percent_diff) < threshold:
        return None
    return "over" if percent_diff > 0 else "under"


def _trailing_months(end_month: date, months: int) -> list[date]:
    """Return the trailing N first-of-month dates ending at ``end_month``.

    Parameters
    ----------
    end_month : datetime.date
        The most recent (first-of-month) date in the window.
    months : int
        The number of months in the window.

    Returns
    -------
    list[datetime.date]
        First-of-month dates, oldest first, ending with ``end_month``.
    """
    result = []
    year, month = end_month.year, end_month.month
    for _ in range(months):
        result.append(date(year, month, 1))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return list(reversed(result))


def _fetch_month_categories(
    client: ynab.ApiClient, budget_id: str, month: date
) -> list[ynab.Category]:
    """Fetch a month's categories, excluding hidden and deleted ones.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id (translated to the SDK's ``plan_id``).
    month : datetime.date
        The first-of-month date to fetch.

    Returns
    -------
    list[ynab.Category]
        Every non-hidden, non-deleted category for the month.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If the YNAB API request fails.
    """
    api = ynab.MonthsApi(client)
    try:
        response = call_with_retry(
            lambda: api.get_plan_month(plan_id=budget_id, month=month)
        )
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return [
        category
        for category in response.data.month.categories
        if not category.hidden and not category.deleted
    ]


def flag_category_spend(
    client: ynab.ApiClient, budget_id: str, month: str, threshold: float = 0.10
) -> list[dict[str, object]]:
    """Flag categories whose spend is beyond threshold of budgeted for a month.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id (translated to the SDK's ``plan_id``).
    month : str
        An ISO-formatted month (e.g. ``"2024-01-01"``) or the literal
        string ``"current"``.
    threshold : float, optional
        Fraction of the budgeted amount beyond which spend is flagged, by
        default ``0.10``.

    Returns
    -------
    list[dict[str, object]]
        One entry per flagged category (categories within threshold are
        omitted), each with ``category_id``, ``category_name``,
        ``budgeted``, ``activity`` (dollars), ``direction``
        (``"over"``/``"under"``), ``percent_diff``, and a plain-language
        ``reason``.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If ``threshold`` is negative, ``month`` is invalid, or the YNAB
        API request fails.
    """
    if threshold < 0:
        raise ToolError("threshold must be >= 0.")
    resolved_month = parse_month(month)
    categories = _fetch_month_categories(client, budget_id, resolved_month)

    flags: list[dict[str, object]] = []
    for category in categories:
        spent = _spent_milli(category)
        direction = _direction(category.budgeted, spent, threshold)
        if direction is None:
            continue
        percent_diff = _percent_diff(category.budgeted, spent)
        budgeted_dollars = _to_dollars(category.budgeted)
        spent_dollars = _to_dollars(spent)
        if category.budgeted == 0:
            reason = (
                f"Spent ${spent_dollars:.2f} against a $0.00 budget "
                "(no budget allocated)."
            )
        else:
            reason = (
                f"Spent ${spent_dollars:.2f} against a ${budgeted_dollars:.2f} "
                f"budget ({abs(percent_diff):.0%} {direction})."  # type: ignore[arg-type]
            )
        flags.append(
            {
                "category_id": category.id,
                "category_name": category.name,
                "budgeted": budgeted_dollars,
                "activity": spent_dollars,
                "direction": direction,
                "percent_diff": percent_diff,
                "reason": reason,
            }
        )
    return flags


def analyze_category_trends(
    client: ynab.ApiClient,
    budget_id: str,
    months: int = 6,
    end_month: str = "current",
    overspend_threshold: float = 0.10,
    majority_ratio: float = 0.5,
) -> list[dict[str, object]]:
    """Detect multi-month overspend/underspend patterns per category.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id (translated to the SDK's ``plan_id``).
    months : int, optional
        The trailing window size in months, by default ``6``.
    end_month : str, optional
        The most recent month in the window: an ISO-formatted month or the
        literal string ``"current"``, by default ``"current"``.
    overspend_threshold : float, optional
        Fraction of budgeted beyond which a single month counts as
        over/under spent, by default ``0.10``.
    majority_ratio : float, optional
        Fraction of the window's months that must show the pattern for it
        to count as a real trend, by default ``0.5``.

    Returns
    -------
    list[dict[str, object]]
        One entry per flagged or insufficient-history category. Flagged
        entries have ``category_id``, ``category_name``, ``budgeted``
        (dollars, most recent month), ``trend``
        (``"rising_overspend"``/``"persistent_underspend"``), a
        ``months_over_threshold`` or ``months_under_threshold`` count,
        ``months_in_window``, and a plain-language ``reason``.
        Insufficient-history entries have ``category_id``,
        ``category_name``, ``trend="insufficient_history"``, and
        ``reason``.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If ``months < 1``, ``overspend_threshold < 0``, ``majority_ratio``
        is outside ``(0, 1]``, ``end_month`` is invalid, or the YNAB API
        request fails for any month in the window.
    """
    if months < 1:
        raise ToolError("months must be >= 1.")
    if overspend_threshold < 0:
        raise ToolError("overspend_threshold must be >= 0.")
    if not (0 < majority_ratio <= 1):
        raise ToolError("majority_ratio must be > 0 and <= 1.")

    resolved_end_month = parse_month(end_month)
    window_months = _trailing_months(resolved_end_month, months)
    monthly_categories = [
        _fetch_month_categories(client, budget_id, m) for m in window_months
    ]
    month_maps = [{c.id: c for c in cats} for cats in monthly_categories]
    all_category_ids = {c.id for cats in monthly_categories for c in cats}

    results: list[dict[str, object]] = []
    for category_id in all_category_ids:
        trailing_count = 0
        for month_map in reversed(month_maps):
            if category_id in month_map:
                trailing_count += 1
            else:
                break

        if trailing_count < months:
            name = next(
                m[category_id].name for m in reversed(month_maps) if category_id in m
            )
            results.append(
                {
                    "category_id": category_id,
                    "category_name": name,
                    "trend": "insufficient_history",
                    "reason": (
                        f"Insufficient history ({trailing_count}/{months} months)."
                    ),
                }
            )
            continue

        latest = month_maps[-1][category_id]
        earliest = month_maps[0][category_id]

        months_over = 0
        months_under = 0
        for month_map in month_maps:
            category = month_map[category_id]
            direction = _direction(
                category.budgeted, _spent_milli(category), overspend_threshold
            )
            if direction == "over":
                months_over += 1
            elif direction == "under":
                months_under += 1

        rising = latest.budgeted > earliest.budgeted
        if rising and months_over / months >= majority_ratio:
            results.append(
                {
                    "category_id": category_id,
                    "category_name": latest.name,
                    "budgeted": _to_dollars(latest.budgeted),
                    "trend": "rising_overspend",
                    "months_over_threshold": months_over,
                    "months_in_window": months,
                    "reason": (
                        f"Budget raised from ${_to_dollars(earliest.budgeted):.2f} "
                        f"to ${_to_dollars(latest.budgeted):.2f} over {months} "
                        f"months but overspent in {months_over}/{months} months."
                    ),
                }
            )
        elif months_under / months >= majority_ratio:
            results.append(
                {
                    "category_id": category_id,
                    "category_name": latest.name,
                    "budgeted": _to_dollars(latest.budgeted),
                    "trend": "persistent_underspend",
                    "months_under_threshold": months_under,
                    "months_in_window": months,
                    "reason": (
                        f"Underspent in {months_under}/{months} months "
                        f"(budget ${_to_dollars(latest.budgeted):.2f})."
                    ),
                }
            )

    return results


def register(mcp: FastMCP, client: ynab.ApiClient, settings: Settings) -> None:
    """Register the spend-analysis tools on ``mcp``.

    Parameters
    ----------
    mcp : fastmcp.FastMCP
        The server to register the tools on.
    client : ynab.ApiClient
        A configured YNAB API client.
    settings : Settings
        The server's parsed configuration, used to resolve a default budget
        id when the caller omits one.
    """

    @mcp.tool(name="flag-category-spend")
    def flag_category_spend_tool(
        month: str, threshold: float = 0.10, budget_id: str | None = None
    ) -> list[dict[str, object]]:
        """Flag categories whose spend is beyond threshold of budgeted for a month.

        Parameters
        ----------
        month : str
            An ISO-formatted month (e.g. ``"2024-01-01"``) or the literal
            string ``"current"``.
        threshold : float, optional
            Fraction of the budgeted amount beyond which spend is flagged,
            by default ``0.10``.
        budget_id : str | None, optional
            The YNAB budget id, by default ``None`` (falls back to
            ``YNAB_DEFAULT_BUDGET_ID``).
        """
        resolved_budget_id = resolve_budget_id(budget_id, settings)
        return flag_category_spend(client, resolved_budget_id, month, threshold)

    @mcp.tool(name="analyze-category-trends")
    def analyze_category_trends_tool(
        months: int = 6,
        end_month: str = "current",
        overspend_threshold: float = 0.10,
        majority_ratio: float = 0.5,
        budget_id: str | None = None,
    ) -> list[dict[str, object]]:
        """Detect multi-month overspend/underspend patterns per category.

        Parameters
        ----------
        months : int, optional
            The trailing window size in months, by default ``6``.
        end_month : str, optional
            The most recent month in the window: an ISO-formatted month or
            the literal string ``"current"``, by default ``"current"``.
        overspend_threshold : float, optional
            Fraction of budgeted beyond which a single month counts as
            over/under spent, by default ``0.10``.
        majority_ratio : float, optional
            Fraction of the window's months that must show the pattern for
            it to count as a real trend, by default ``0.5``.
        budget_id : str | None, optional
            The YNAB budget id, by default ``None`` (falls back to
            ``YNAB_DEFAULT_BUDGET_ID``).
        """
        resolved_budget_id = resolve_budget_id(budget_id, settings)
        return analyze_category_trends(
            client,
            resolved_budget_id,
            months=months,
            end_month=end_month,
            overspend_threshold=overspend_threshold,
            majority_ratio=majority_ratio,
        )
