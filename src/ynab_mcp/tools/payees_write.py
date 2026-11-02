"""manage-payees tool: rename or merge payees."""

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
from ynab_mcp.write_summaries import pending_payee_merge, pending_payee_rename


def rename_payee(
    client: ynab.ApiClient, budget_id: str, payee_id: str, new_name: str
) -> ynab.Payee:
    """Rename a payee.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id (translated to the SDK's ``plan_id``).
    payee_id : str
        The id of the payee to rename.
    new_name : str
        The payee's new name.

    Returns
    -------
    ynab.Payee
        The renamed payee.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If the YNAB API request fails.
    """
    api = ynab.PayeesApi(client)
    try:
        response = call_with_retry(
            lambda: api.update_payee(
                plan_id=budget_id,
                payee_id=payee_id,
                data=ynab.PatchPayeeWrapper(payee=ynab.SavePayee(name=new_name)),
            )
        )
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return response.data.payee


def merge_payees(
    client: ynab.ApiClient,
    budget_id: str,
    source_payee_id: str,
    target_payee_id: str,
) -> ynab.Payee:
    """Merge one payee into another.

    YNAB has no explicit merge endpoint: renaming a payee to exactly match
    an existing payee's name is what triggers a server-side merge. This
    reads the target payee's current name, then renames the source payee
    to match it -- YNAB retires the source payee automatically.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id (translated to the SDK's ``plan_id``).
    source_payee_id : str
        The id of the payee that will be merged away.
    target_payee_id : str
        The id of the payee that survives the merge.

    Returns
    -------
    ynab.Payee
        The surviving (target) payee, as returned by the rename call.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If the YNAB API request fails.
    """
    api = ynab.PayeesApi(client)
    try:
        target = call_with_retry(
            lambda: api.get_payee_by_id(plan_id=budget_id, payee_id=target_payee_id)
        )
        response = call_with_retry(
            lambda: api.update_payee(
                plan_id=budget_id,
                payee_id=source_payee_id,
                data=ynab.PatchPayeeWrapper(
                    payee=ynab.SavePayee(name=target.data.payee.name)
                ),
            )
        )
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return response.data.payee


def register(mcp: FastMCP, client: ynab.ApiClient, settings: Settings) -> None:
    """Register the ``manage-payees`` tool on ``mcp``.

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

    @mcp.tool(name="manage-payees")
    async def manage_payees_tool(
        operation: Literal["rename", "merge"],
        ctx: Context,
        payee_id: str | None = None,
        new_name: str | None = None,
        source_payee_id: str | None = None,
        target_payee_id: str | None = None,
        budget_id: str | None = None,
    ) -> dict[str, object] | InputRequiredResult:
        """Rename or merge a payee.

        Parameters
        ----------
        operation : {"rename", "merge"}
            Which operation to perform.
        payee_id : str | None, optional
            Required for ``"rename"``: the payee to rename.
        new_name : str | None, optional
            Required for ``"rename"``: the payee's new name.
        source_payee_id : str | None, optional
            Required for ``"merge"``: the payee that will be merged away.
        target_payee_id : str | None, optional
            Required for ``"merge"``: the payee that survives the merge.
        budget_id : str | None, optional
            The YNAB budget id, by default ``None`` (falls back to
            ``YNAB_DEFAULT_BUDGET_ID``).
        """
        require_writable(settings)
        resolved_budget_id = resolve_budget_id(budget_id, settings)
        arguments = {
            "operation": operation,
            "payee_id": payee_id,
            "new_name": new_name,
            "source_payee_id": source_payee_id,
            "target_payee_id": target_payee_id,
        }
        if operation == "rename":
            if payee_id is None or new_name is None:
                raise ToolError("rename requires payee_id and new_name.")
            pending = pending_payee_rename(
                client, resolved_budget_id, payee_id, new_name
            )
            write = partial(
                rename_payee, client, resolved_budget_id, payee_id, new_name
            )
        else:
            if source_payee_id is None or target_payee_id is None:
                raise ToolError("merge requires source_payee_id and target_payee_id.")
            pending = pending_payee_merge(
                client, resolved_budget_id, source_payee_id, target_payee_id
            )
            write = partial(
                merge_payees,
                client,
                resolved_budget_id,
                source_payee_id,
                target_payee_id,
            )
        asked = await require_approval(
            ctx,
            settings,
            tool_name="manage-payees",
            budget_id=resolved_budget_id,
            arguments=arguments,
            pending=pending,
        )
        if asked is not None:
            return asked

        payee = await anyio.to_thread.run_sync(write)
        return payee.model_dump(mode="json")
