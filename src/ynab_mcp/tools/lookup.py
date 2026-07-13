"""lookup-entity-by-id tool: fetch a single YNAB entity of any known type."""

from typing import Literal

import ynab
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from ynab_mcp.client import resolve_budget_id
from ynab_mcp.config import Settings
from ynab_mcp.errors import translate_api_exception
from ynab_mcp.tools.months import parse_month

EntityType = Literal["account", "category", "payee", "transaction", "month"]

_KNOWN_ENTITY_TYPES = "account, category, payee, transaction, month"


def lookup_entity_by_id(
    client: ynab.ApiClient, budget_id: str, entity_type: EntityType, entity_id: str
) -> (
    ynab.Account
    | ynab.Category
    | ynab.Payee
    | ynab.TransactionDetail
    | ynab.MonthDetail
):
    """Fetch a single YNAB entity by its id.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id (translated to the SDK's ``plan_id``).
    entity_type : {"account", "category", "payee", "transaction", "month"}
        Which kind of entity ``entity_id`` refers to.
    entity_id : str
        The entity's id. For ``entity_type="month"`` this is an ISO date
        (e.g. ``"2024-01-01"``) or the literal ``"current"``, not a UUID.

    Returns
    -------
    ynab.Account | ynab.Category | ynab.Payee | ynab.TransactionDetail |
    ynab.MonthDetail
        The resolved entity.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If ``entity_type`` is not one of the known values, if ``entity_id``
        is an invalid month value, or if the YNAB API request fails.
    """
    try:
        if entity_type == "account":
            result: (
                ynab.Account
                | ynab.Category
                | ynab.Payee
                | ynab.TransactionDetail
                | ynab.MonthDetail
            ) = (
                ynab.AccountsApi(client)
                .get_account_by_id(plan_id=budget_id, account_id=entity_id)  # type: ignore[arg-type]
                .data.account
            )
        elif entity_type == "category":
            result = (
                ynab.CategoriesApi(client)
                .get_category_by_id(plan_id=budget_id, category_id=entity_id)
                .data.category
            )
        elif entity_type == "payee":
            result = (
                ynab.PayeesApi(client)
                .get_payee_by_id(plan_id=budget_id, payee_id=entity_id)
                .data.payee
            )
        elif entity_type == "transaction":
            result = (
                ynab.TransactionsApi(client)
                .get_transaction_by_id(plan_id=budget_id, transaction_id=entity_id)
                .data.transaction
            )
        elif entity_type == "month":
            resolved_month = parse_month(entity_id)
            result = (
                ynab.MonthsApi(client)
                .get_plan_month(plan_id=budget_id, month=resolved_month)
                .data.month
            )
        else:
            raise ToolError(
                f"Unknown entity_type {entity_type!r}. Expected one of: "
                f"{_KNOWN_ENTITY_TYPES}."
            )
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return result


def register(mcp: FastMCP, client: ynab.ApiClient, settings: Settings) -> None:
    """Register the ``lookup-entity-by-id`` tool on ``mcp``.

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

    @mcp.tool(name="lookup-entity-by-id")
    def lookup_entity_by_id_tool(
        entity_type: EntityType, entity_id: str, budget_id: str | None = None
    ) -> dict[str, object]:
        """Fetch a single YNAB entity by its id.

        Parameters
        ----------
        entity_type : {"account", "category", "payee", "transaction", "month"}
            Which kind of entity ``entity_id`` refers to.
        entity_id : str
            The entity's id. For ``entity_type="month"`` this is an ISO
            date (e.g. ``"2024-01-01"``) or the literal ``"current"``.
        budget_id : str | None, optional
            The YNAB budget id, by default ``None`` (falls back to
            ``YNAB_DEFAULT_BUDGET_ID``).
        """
        resolved_budget_id = resolve_budget_id(budget_id, settings)
        entity = lookup_entity_by_id(client, resolved_budget_id, entity_type, entity_id)
        return entity.model_dump(mode="json")
