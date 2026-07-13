"""list-transactions tool: enumerate transactions in a YNAB budget."""

from datetime import date
from typing import Union, cast

import ynab
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from ynab_mcp.client import resolve_budget_id
from ynab_mcp.config import Settings
from ynab_mcp.errors import translate_api_exception


def list_transactions(
    client: ynab.ApiClient,
    budget_id: str,
    account_id: str | None = None,
    category_id: str | None = None,
    payee_id: str | None = None,
    since_date: date | None = None,
    until_date: date | None = None,
) -> list[ynab.TransactionDetail]:
    """List transactions in a YNAB budget, optionally filtered.

    The YNAB SDK exposes one entity filter per endpoint
    (``get_transactions_by_account`` / ``_by_category`` / ``_by_payee``),
    not combinable server-side, so at most one of ``account_id``,
    ``category_id``, ``payee_id`` may be given.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id (translated to the SDK's ``plan_id``).
    account_id : str | None, optional
        Restrict to transactions on this account, by default ``None``.
    category_id : str | None, optional
        Restrict to transactions in this category, by default ``None``.
    payee_id : str | None, optional
        Restrict to transactions with this payee, by default ``None``.
    since_date : datetime.date | None, optional
        Only include transactions on or after this date, by default
        ``None``.
    until_date : datetime.date | None, optional
        Only include transactions on or before this date, by default
        ``None``.

    Returns
    -------
    list[ynab.TransactionDetail]
        Matching transactions.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If more than one entity filter is given, or if the YNAB API
        request fails.
    """
    entity_filters = [f for f in (account_id, category_id, payee_id) if f is not None]
    if len(entity_filters) > 1:
        raise ToolError(
            "list-transactions accepts at most one of account_id, "
            "category_id, payee_id."
        )

    api = ynab.TransactionsApi(client)
    try:
        if account_id is not None:
            response: Union[
                ynab.TransactionsResponse, ynab.HybridTransactionsResponse
            ] = api.get_transactions_by_account(
                plan_id=budget_id,
                account_id=account_id,
                since_date=since_date,
                until_date=until_date,
            )
        elif category_id is not None:
            response = api.get_transactions_by_category(
                plan_id=budget_id,
                category_id=category_id,
                since_date=since_date,
                until_date=until_date,
            )
        elif payee_id is not None:
            response = api.get_transactions_by_payee(
                plan_id=budget_id,
                payee_id=payee_id,
                since_date=since_date,
                until_date=until_date,
            )
        else:
            response = api.get_transactions(
                plan_id=budget_id, since_date=since_date, until_date=until_date
            )
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return cast(list[ynab.TransactionDetail], response.data.transactions)


def register(mcp: FastMCP, client: ynab.ApiClient, settings: Settings) -> None:
    """Register the ``list-transactions`` tool on ``mcp``.

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

    @mcp.tool(name="list-transactions")
    def list_transactions_tool(
        budget_id: str | None = None,
        account_id: str | None = None,
        category_id: str | None = None,
        payee_id: str | None = None,
        since_date: date | None = None,
        until_date: date | None = None,
    ) -> list[dict[str, object]]:
        """List transactions in a YNAB budget, optionally filtered.

        At most one of ``account_id``, ``category_id``, ``payee_id`` may
        be given.

        Parameters
        ----------
        budget_id : str | None, optional
            The YNAB budget id, by default ``None`` (falls back to
            ``YNAB_DEFAULT_BUDGET_ID``).
        account_id : str | None, optional
            Restrict to transactions on this account, by default ``None``.
        category_id : str | None, optional
            Restrict to transactions in this category, by default ``None``.
        payee_id : str | None, optional
            Restrict to transactions with this payee, by default ``None``.
        since_date : datetime.date | None, optional
            Only include transactions on or after this date, by default
            ``None``.
        until_date : datetime.date | None, optional
            Only include transactions on or before this date, by default
            ``None``.
        """
        resolved_budget_id = resolve_budget_id(budget_id, settings)
        transactions = list_transactions(
            client,
            resolved_budget_id,
            account_id=account_id,
            category_id=category_id,
            payee_id=payee_id,
            since_date=since_date,
            until_date=until_date,
        )
        return [t.model_dump(mode="json") for t in transactions]
