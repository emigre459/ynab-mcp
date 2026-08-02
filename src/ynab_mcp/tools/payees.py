"""list-payees tool: enumerate payees in a YNAB budget."""

import ynab
from fastmcp import FastMCP

from ynab_mcp.client import call_with_retry, resolve_budget_id
from ynab_mcp.config import Settings
from ynab_mcp.errors import translate_api_exception


def list_payees(client: ynab.ApiClient, budget_id: str) -> list[ynab.Payee]:
    """List every payee in a YNAB budget.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id (translated to the SDK's ``plan_id``).

    Returns
    -------
    list[ynab.Payee]
        One entry per payee in the budget.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If the YNAB API request fails.
    """
    api = ynab.PayeesApi(client)
    try:
        response = call_with_retry(lambda: api.get_payees(plan_id=budget_id))
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return response.data.payees


def register(mcp: FastMCP, client: ynab.ApiClient, settings: Settings) -> None:
    """Register the ``list-payees`` tool on ``mcp``.

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

    @mcp.tool(name="list-payees")
    def list_payees_tool(budget_id: str | None = None) -> list[dict[str, object]]:
        """List every payee in a YNAB budget.

        Parameters
        ----------
        budget_id : str | None, optional
            The YNAB budget id, by default ``None`` (falls back to
            ``YNAB_DEFAULT_BUDGET_ID``).
        """
        resolved_budget_id = resolve_budget_id(budget_id, settings)
        payees = list_payees(client, resolved_budget_id)
        return [p.model_dump(mode="json") for p in payees]
