"""get-month-info tool: fetch YNAB budget totals for a single month."""

from datetime import date

import ynab
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from ynab_mcp.client import resolve_budget_id
from ynab_mcp.config import Settings
from ynab_mcp.errors import translate_api_exception


def parse_month(value: str) -> date:
    """Parse a YNAB month value into a ``datetime.date``.

    Parameters
    ----------
    value : str
        An ISO-formatted month (e.g. ``"2024-01-01"``) or the literal
        string ``"current"`` for the current calendar month (UTC).

    Returns
    -------
    datetime.date
        The first day of the resolved month.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If ``value`` is not a valid ISO date and not ``"current"``.
    """
    if value == "current":
        return date.today().replace(day=1)
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ToolError(
            f"Invalid month {value!r}: expected an ISO date (YYYY-MM-DD) or "
            "'current'."
        ) from exc


def get_month_info(
    client: ynab.ApiClient, budget_id: str, month: str
) -> ynab.MonthDetail:
    """Get YNAB budget totals and category detail for a single month.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id (translated to the SDK's ``plan_id``).
    month : str
        An ISO-formatted month (e.g. ``"2024-01-01"``) or the literal
        string ``"current"``.

    Returns
    -------
    ynab.MonthDetail
        Budget totals and category detail for the month.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If ``month`` is invalid, or if the YNAB API request fails.
    """
    resolved_month = parse_month(month)
    api = ynab.MonthsApi(client)
    try:
        response = api.get_plan_month(plan_id=budget_id, month=resolved_month)
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return response.data.month


def register(mcp: FastMCP, client: ynab.ApiClient, settings: Settings) -> None:
    """Register the ``get-month-info`` tool on ``mcp``.

    Parameters
    ----------
    mcp : fastmcp.FastMCP
        The server to register the tool on.
    client : ynab.ApiClient
        A configured YNAB API client.
    settings : Settings
        The server's parsed configuration, used to resolve a default budget
        id when the caller omits one.
    """

    @mcp.tool(name="get-month-info")
    def get_month_info_tool(
        month: str, budget_id: str | None = None
    ) -> dict[str, object]:
        """Get YNAB budget totals and category detail for a single month.

        Parameters
        ----------
        month : str
            An ISO-formatted month (e.g. ``"2024-01-01"``) or the literal
            string ``"current"``.
        budget_id : str | None, optional
            The YNAB budget id, by default ``None`` (falls back to
            ``YNAB_DEFAULT_BUDGET_ID``).
        """
        resolved_budget_id = resolve_budget_id(budget_id, settings)
        month_info = get_month_info(client, resolved_budget_id, month)
        return month_info.model_dump(mode="json")
