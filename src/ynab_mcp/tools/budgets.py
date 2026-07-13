"""list-budgets tool: enumerate the caller's YNAB budgets."""

import ynab
from fastmcp import FastMCP

from ynab_mcp.errors import translate_api_exception


def list_budgets(client: ynab.ApiClient) -> list[ynab.PlanSummary]:
    """List every YNAB budget the configured token can access.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.

    Returns
    -------
    list[ynab.PlanSummary]
        One summary per budget.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If the YNAB API request fails.
    """
    api = ynab.PlansApi(client)
    try:
        response = api.get_plans()
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return response.data.plans


def register(mcp: FastMCP, client: ynab.ApiClient) -> None:
    """Register the ``list-budgets`` tool on ``mcp``.

    Parameters
    ----------
    mcp : fastmcp.FastMCP
        The server to register the tool on.
    client : ynab.ApiClient
        A configured YNAB API client.
    """

    @mcp.tool(name="list-budgets")
    def list_budgets_tool() -> list[dict[str, object]]:
        """List every YNAB budget the configured token can access."""
        budgets = list_budgets(client)
        return [b.model_dump(mode="json") for b in budgets]
