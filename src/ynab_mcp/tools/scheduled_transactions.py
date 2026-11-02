"""manage-scheduled-transaction tool: create/update/delete a recurring transaction."""

from datetime import date
from functools import partial
from typing import Literal

import anyio.to_thread
import ynab
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from mcp_types import InputRequiredResult

from ynab_mcp.approval import require_approval
from ynab_mcp.client import call_with_retry, require_writable, resolve_budget_id
from ynab_mcp.config import Settings
from ynab_mcp.errors import translate_api_exception
from ynab_mcp.write_summaries import pending_scheduled_write


def create_scheduled_transaction(
    client: ynab.ApiClient,
    budget_id: str,
    account_id: str,
    date: date,
    amount: int,
    frequency: str,
    payee_id: str | None = None,
    payee_name: str | None = None,
    category_id: str | None = None,
    memo: str | None = None,
    flag_color: str | None = None,
) -> ynab.ScheduledTransactionDetail:
    """Create a recurring (scheduled) transaction.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id (translated to the SDK's ``plan_id``).
    account_id : str
        The account the scheduled transaction belongs to.
    date : datetime.date
        The first scheduled date.
    amount : int
        The transaction amount in milliunits.
    frequency : str
        How often the transaction recurs (e.g. ``"monthly"``).
    payee_id : str | None, optional
        The transaction's payee, by id, by default ``None``.
    payee_name : str | None, optional
        The transaction's payee, by name, by default ``None``.
    category_id : str | None, optional
        The transaction's category, by default ``None``.
    memo : str | None, optional
        A free-text memo, by default ``None``.
    flag_color : str | None, optional
        A YNAB flag color, by default ``None``.

    Returns
    -------
    ynab.ScheduledTransactionDetail
        The created scheduled transaction.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If the YNAB API request fails.
    """
    api = ynab.ScheduledTransactionsApi(client)
    try:
        response = call_with_retry(
            lambda: api.create_scheduled_transaction(
                plan_id=budget_id,
                data=ynab.PostScheduledTransactionWrapper(
                    scheduled_transaction=ynab.SaveScheduledTransaction(
                        account_id=account_id,
                        var_date=date,
                        amount=amount,
                        payee_id=payee_id,
                        payee_name=payee_name,
                        category_id=category_id,
                        memo=memo,
                        flag_color=flag_color,
                        frequency=frequency,
                    )
                ),
            ),
            include_5xx=False,
        )
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return response.data.scheduled_transaction


def update_scheduled_transaction(
    client: ynab.ApiClient,
    budget_id: str,
    scheduled_transaction_id: str,
    account_id: str,
    date: date,
    amount: int,
    frequency: str,
    payee_id: str | None = None,
    payee_name: str | None = None,
    category_id: str | None = None,
    memo: str | None = None,
    flag_color: str | None = None,
) -> ynab.ScheduledTransactionDetail:
    """Update a recurring (scheduled) transaction.

    YNAB's update endpoint is a full replace (PUT): every field must be
    resupplied, matching ``create_scheduled_transaction``'s signature.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id (translated to the SDK's ``plan_id``).
    scheduled_transaction_id : str
        The id of the scheduled transaction to update.
    account_id : str
        The account the scheduled transaction belongs to.
    date : datetime.date
        The next scheduled date.
    amount : int
        The transaction amount in milliunits.
    frequency : str
        How often the transaction recurs (e.g. ``"monthly"``).
    payee_id : str | None, optional
        The transaction's payee, by id, by default ``None``.
    payee_name : str | None, optional
        The transaction's payee, by name, by default ``None``.
    category_id : str | None, optional
        The transaction's category, by default ``None``.
    memo : str | None, optional
        A free-text memo, by default ``None``.
    flag_color : str | None, optional
        A YNAB flag color, by default ``None``.

    Returns
    -------
    ynab.ScheduledTransactionDetail
        The updated scheduled transaction.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If the YNAB API request fails.
    """
    api = ynab.ScheduledTransactionsApi(client)
    try:
        response = call_with_retry(
            lambda: api.update_scheduled_transaction(
                plan_id=budget_id,
                scheduled_transaction_id=scheduled_transaction_id,
                put_scheduled_transaction_wrapper=ynab.PutScheduledTransactionWrapper(
                    scheduled_transaction=ynab.SaveScheduledTransaction(
                        account_id=account_id,
                        var_date=date,
                        amount=amount,
                        payee_id=payee_id,
                        payee_name=payee_name,
                        category_id=category_id,
                        memo=memo,
                        flag_color=flag_color,
                        frequency=frequency,
                    )
                ),
            )
        )
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return response.data.scheduled_transaction


def delete_scheduled_transaction(
    client: ynab.ApiClient, budget_id: str, scheduled_transaction_id: str
) -> ynab.ScheduledTransactionDetail:
    """Delete a recurring (scheduled) transaction.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id (translated to the SDK's ``plan_id``).
    scheduled_transaction_id : str
        The id of the scheduled transaction to delete.

    Returns
    -------
    ynab.ScheduledTransactionDetail
        The deleted scheduled transaction.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If the YNAB API request fails.
    """
    api = ynab.ScheduledTransactionsApi(client)
    try:
        response = call_with_retry(
            lambda: api.delete_scheduled_transaction(
                plan_id=budget_id, scheduled_transaction_id=scheduled_transaction_id
            )
        )
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return response.data.scheduled_transaction


def register(mcp: FastMCP, client: ynab.ApiClient, settings: Settings) -> None:
    """Register the ``manage-scheduled-transaction`` tool on ``mcp``.

    Parameters
    ----------
    mcp : fastmcp.FastMCP
        The server to register the tool on.
    client : ynab.ApiClient
        A configured YNAB API client.
    settings : Settings
        The server's parsed configuration, used to resolve a default budget
        id when the caller omits one, and to enforce ``YNAB_READ_ONLY``.
    """

    @mcp.tool(name="manage-scheduled-transaction")
    async def manage_scheduled_transaction_tool(
        operation: Literal["create", "update", "delete"],
        ctx: Context,
        scheduled_transaction_id: str | None = None,
        account_id: str | None = None,
        date: date | None = None,
        amount: int | None = None,
        frequency: str | None = None,
        payee_id: str | None = None,
        payee_name: str | None = None,
        category_id: str | None = None,
        memo: str | None = None,
        flag_color: str | None = None,
        budget_id: str | None = None,
    ) -> dict[str, object] | InputRequiredResult:
        """Create, update, or delete a recurring (scheduled) transaction.

        Parameters
        ----------
        operation : {"create", "update", "delete"}
            Which operation to perform.
        scheduled_transaction_id : str | None, optional
            Required for ``"update"`` and ``"delete"``.
        account_id : str | None, optional
            Required for ``"create"`` and ``"update"``.
        date : datetime.date | None, optional
            The scheduled date. Required for ``"create"`` and ``"update"``.
        amount : int | None, optional
            The transaction amount in milliunits. Required for
            ``"create"`` and ``"update"``.
        frequency : str | None, optional
            How often the transaction recurs (e.g. ``"monthly"``).
            Required for ``"create"`` and ``"update"``.
        payee_id : str | None, optional
            The transaction's payee, by id, by default ``None``.
        payee_name : str | None, optional
            The transaction's payee, by name, by default ``None``.
        category_id : str | None, optional
            The transaction's category, by default ``None``.
        memo : str | None, optional
            A free-text memo, by default ``None``.
        flag_color : str | None, optional
            A YNAB flag color, by default ``None``.
        budget_id : str | None, optional
            The YNAB budget id, by default ``None`` (falls back to
            ``YNAB_DEFAULT_BUDGET_ID``).
        """
        require_writable(settings)
        resolved_budget_id = resolve_budget_id(budget_id, settings)

        fields: dict[str, object] = {
            "account_id": account_id,
            "date": date,
            "amount": amount,
            "frequency": frequency,
            "payee_id": payee_id,
            "payee_name": payee_name,
            "category_id": category_id,
            "memo": memo,
            "flag_color": flag_color,
        }
        optional = {
            "payee_id": payee_id,
            "payee_name": payee_name,
            "category_id": category_id,
            "memo": memo,
            "flag_color": flag_color,
        }
        if operation == "delete":
            if scheduled_transaction_id is None:
                raise ToolError("delete requires scheduled_transaction_id.")
            write = partial(
                delete_scheduled_transaction,
                client,
                resolved_budget_id,
                scheduled_transaction_id,
            )
        else:
            if (
                account_id is None
                or date is None
                or amount is None
                or frequency is None
            ):
                raise ToolError(
                    f"{operation} requires account_id, date, amount, and frequency."
                )
            if operation == "create":
                write = partial(
                    create_scheduled_transaction,
                    client,
                    resolved_budget_id,
                    account_id,
                    date,
                    amount,
                    frequency,
                    **optional,
                )
            else:
                if scheduled_transaction_id is None:
                    raise ToolError("update requires scheduled_transaction_id.")
                write = partial(
                    update_scheduled_transaction,
                    client,
                    resolved_budget_id,
                    scheduled_transaction_id,
                    account_id,
                    date,
                    amount,
                    frequency,
                    **optional,
                )

        asked = await require_approval(
            ctx,
            settings,
            tool_name="manage-scheduled-transaction",
            budget_id=resolved_budget_id,
            arguments={
                "operation": operation,
                "scheduled_transaction_id": scheduled_transaction_id,
                **fields,
            },
            pending=pending_scheduled_write(
                client, resolved_budget_id, operation, scheduled_transaction_id, fields
            ),
        )
        if asked is not None:
            return asked
        scheduled_transaction = await anyio.to_thread.run_sync(write)
        return scheduled_transaction.model_dump(mode="json")
