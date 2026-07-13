"""flag-category-spend and analyze-category-trends tools: budget vs. actual spend analysis."""

from datetime import date

import ynab


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
    if abs(percent_diff) < threshold:
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
