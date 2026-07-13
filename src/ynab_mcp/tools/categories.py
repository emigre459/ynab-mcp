"""list-categories tool: enumerate categories in a YNAB budget."""

import ynab
from fastmcp import FastMCP

from ynab_mcp.client import resolve_budget_id
from ynab_mcp.config import Settings
from ynab_mcp.errors import translate_api_exception


def list_categories(client: ynab.ApiClient, budget_id: str) -> list[ynab.Category]:
    """List every category in a YNAB budget, flattened across category groups.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id (translated to the SDK's ``plan_id``).

    Returns
    -------
    list[ynab.Category]
        Every category across every category group. Each entry carries its
        own ``category_group_name``, so the flattening loses no context.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If the YNAB API request fails.
    """
    api = ynab.CategoriesApi(client)
    try:
        response = api.get_categories(plan_id=budget_id)
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return [
        category
        for group in response.data.category_groups
        for category in group.categories
    ]


def register(mcp: FastMCP, client: ynab.ApiClient, settings: Settings) -> None:
    """Register the ``list-categories`` tool on ``mcp``.

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

    @mcp.tool(name="list-categories")
    def list_categories_tool(
        budget_id: str | None = None,
    ) -> list[dict[str, object]]:
        """List every category in a YNAB budget.

        Parameters
        ----------
        budget_id : str | None, optional
            The YNAB budget id, by default ``None`` (falls back to
            ``YNAB_DEFAULT_BUDGET_ID``).
        """
        resolved_budget_id = resolve_budget_id(budget_id, settings)
        categories = list_categories(client, resolved_budget_id)
        return [c.model_dump(mode="json") for c in categories]
