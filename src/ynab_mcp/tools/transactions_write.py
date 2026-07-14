"""bulk-manage-transactions tool: create/update/delete transactions in one call."""

from typing import Literal, TypedDict

import ynab
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from ynab_mcp.client import require_writable, resolve_budget_id
from ynab_mcp.config import Settings
from ynab_mcp.errors import translate_api_exception


class TransactionOperationResult(TypedDict):
    """The outcome of one operation within a ``bulk-manage-transactions`` call."""

    action: str
    id: str | None
    status: Literal["ok", "error"]
    detail: str | None


def _build_new_transaction(operation: dict[str, object]) -> ynab.NewTransaction:
    """Build a ``NewTransaction`` from a raw ``create`` operation dict."""
    return ynab.NewTransaction(
        account_id=operation.get("account_id"),
        date=operation.get("date"),
        amount=operation.get("amount"),
        payee_id=operation.get("payee_id"),
        payee_name=operation.get("payee_name"),
        category_id=operation.get("category_id"),
        memo=operation.get("memo"),
        cleared=operation.get("cleared"),
        approved=operation.get("approved"),
        flag_color=operation.get("flag_color"),
    )


def _build_updated_transaction(
    operation: dict[str, object],
) -> ynab.SaveTransactionWithIdOrImportId:
    """Build a ``SaveTransactionWithIdOrImportId`` from a raw ``update`` dict."""
    return ynab.SaveTransactionWithIdOrImportId(
        id=operation.get("id"),
        account_id=operation.get("account_id"),
        date=operation.get("date"),
        amount=operation.get("amount"),
        payee_id=operation.get("payee_id"),
        payee_name=operation.get("payee_name"),
        category_id=operation.get("category_id"),
        memo=operation.get("memo"),
        cleared=operation.get("cleared"),
        approved=operation.get("approved"),
        flag_color=operation.get("flag_color"),
    )


def bulk_manage_transactions(
    client: ynab.ApiClient, budget_id: str, operations: list[dict[str, object]]
) -> list[TransactionOperationResult]:
    """Create, update, and/or delete multiple transactions in one call.

    The YNAB API has no single bulk endpoint spanning create/update/delete:
    creates and updates each accept an array in one call, but delete is
    one-transaction-at-a-time. This groups ``operations`` by ``action`` and
    issues at most three physical API calls (one grouped create, one
    grouped update, a loop of deletes). A failure in one group does not
    block the others -- results are reported per item instead of raised.
    If a grouped create/update call itself fails, every item in that group
    is marked as an error with the same translated detail message, since
    the SDK does not report which array element specifically failed.
    Assumes YNAB preserves array order between request and response.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id (translated to the SDK's ``plan_id``).
    operations : list[dict[str, object]]
        Each dict has a required ``"action"`` of ``"create"``,
        ``"update"``, or ``"delete"``. ``"create"`` requires
        ``"account_id"``; ``"update"`` and ``"delete"`` require ``"id"``.
        Other keys (``account_id``, ``date``, ``amount``, ``payee_id``,
        ``payee_name``, ``category_id``, ``memo``, ``cleared``,
        ``approved``, ``flag_color``) map to the corresponding transaction
        fields.

    Returns
    -------
    list[TransactionOperationResult]
        One result per input operation, in the same order.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If ``operations`` is empty, or any operation has an invalid or
        missing ``action``/``id``/``account_id``. Per-item YNAB API
        failures do NOT raise -- they appear in the returned results.
    """
    if not operations:
        raise ToolError("bulk-manage-transactions requires at least one operation.")

    for index, operation in enumerate(operations):
        action = operation.get("action")
        if action not in ("create", "update", "delete"):
            raise ToolError(
                f"operations[{index}]: action must be one of 'create', "
                "'update', 'delete'."
            )
        if action in ("update", "delete") and not operation.get("id"):
            raise ToolError(f"operations[{index}]: {action} requires 'id'.")
        if action == "create" and not operation.get("account_id"):
            raise ToolError(f"operations[{index}]: create requires 'account_id'.")

    api = ynab.TransactionsApi(client)
    results: dict[int, TransactionOperationResult] = {}

    create_indices = [i for i, op in enumerate(operations) if op["action"] == "create"]
    if create_indices:
        try:
            response = api.create_transaction(
                plan_id=budget_id,
                data=ynab.PostTransactionsWrapper(
                    transactions=[
                        _build_new_transaction(operations[i]) for i in create_indices
                    ]
                ),
            )
            created = response.data.transactions or []
            for i, transaction in zip(create_indices, created):
                results[i] = {
                    "action": "create",
                    "id": transaction.id,
                    "status": "ok",
                    "detail": None,
                }
            for i in create_indices:
                if i not in results:
                    results[i] = {
                        "action": "create",
                        "id": None,
                        "status": "error",
                        "detail": (
                            "YNAB's response did not include a result for "
                            "this create operation."
                        ),
                    }
        except ynab.ApiException as exc:
            detail = str(translate_api_exception(exc))
            for i in create_indices:
                results[i] = {
                    "action": "create",
                    "id": None,
                    "status": "error",
                    "detail": detail,
                }

    update_indices = [i for i, op in enumerate(operations) if op["action"] == "update"]
    if update_indices:
        try:
            response = api.update_transactions(
                plan_id=budget_id,
                data=ynab.PatchTransactionsWrapper(
                    transactions=[
                        _build_updated_transaction(operations[i])
                        for i in update_indices
                    ]
                ),
            )
            updated = response.data.transactions or []
            for i, transaction in zip(update_indices, updated):
                results[i] = {
                    "action": "update",
                    "id": transaction.id,
                    "status": "ok",
                    "detail": None,
                }
            for i in update_indices:
                if i not in results:
                    results[i] = {
                        "action": "update",
                        "id": str(operations[i]["id"]),
                        "status": "error",
                        "detail": (
                            "YNAB's response did not include a result for "
                            "this update operation."
                        ),
                    }
        except ynab.ApiException as exc:
            detail = str(translate_api_exception(exc))
            for i in update_indices:
                results[i] = {
                    "action": "update",
                    "id": str(operations[i]["id"]),
                    "status": "error",
                    "detail": detail,
                }

    delete_indices = [i for i, op in enumerate(operations) if op["action"] == "delete"]
    for i in delete_indices:
        transaction_id = str(operations[i]["id"])
        try:
            api.delete_transaction(plan_id=budget_id, transaction_id=transaction_id)
            results[i] = {
                "action": "delete",
                "id": transaction_id,
                "status": "ok",
                "detail": None,
            }
        except ynab.ApiException as exc:
            results[i] = {
                "action": "delete",
                "id": transaction_id,
                "status": "error",
                "detail": str(translate_api_exception(exc)),
            }

    return [results[i] for i in range(len(operations))]


def register(mcp: FastMCP, client: ynab.ApiClient, settings: Settings) -> None:
    """Register the ``bulk-manage-transactions`` tool on ``mcp``.

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

    @mcp.tool(name="bulk-manage-transactions")
    def bulk_manage_transactions_tool(
        operations: list[dict[str, object]], budget_id: str | None = None
    ) -> list[TransactionOperationResult]:
        """Create, update, and/or delete multiple transactions in one call.

        Parameters
        ----------
        operations : list[dict[str, object]]
            Each dict has a required ``"action"`` of ``"create"``,
            ``"update"``, or ``"delete"``, plus the relevant transaction
            fields. See ``bulk_manage_transactions`` for the full field
            list.
        budget_id : str | None, optional
            The YNAB budget id, by default ``None`` (falls back to
            ``YNAB_DEFAULT_BUDGET_ID``).
        """
        require_writable(settings)
        resolved_budget_id = resolve_budget_id(budget_id, settings)
        return bulk_manage_transactions(client, resolved_budget_id, operations)
