"""manage-budgeted-amount tool: assign or move budgeted amounts between categories."""

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
from ynab_mcp.tools.months import parse_month
from ynab_mcp.write_summaries import pending_budget_assign, pending_budget_move


def assign_budgeted_amount(
    client: ynab.ApiClient, budget_id: str, month: str, category_id: str, amount: int
) -> ynab.Category:
    """Set a category's budgeted (assigned) amount for a month.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id (translated to the SDK's ``plan_id``).
    month : str
        An ISO-formatted month (e.g. ``"2024-01-01"``) or ``"current"``.
    category_id : str
        The category to update.
    amount : int
        The absolute budgeted amount, in milliunits.

    Returns
    -------
    ynab.Category
        The updated category.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If ``month`` is invalid, or if the YNAB API request fails.
    """
    resolved_month = parse_month(month)
    api = ynab.CategoriesApi(client)
    try:
        response = call_with_retry(
            lambda: api.update_month_category(
                plan_id=budget_id,
                month=resolved_month,
                category_id=category_id,
                data=ynab.PatchMonthCategoryWrapper(
                    category=ynab.SaveMonthCategory(budgeted=amount)
                ),
            )
        )
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return response.data.category


def move_budgeted_amount(
    client: ynab.ApiClient,
    budget_id: str,
    month: str,
    from_category_id: str,
    to_category_id: str,
    amount: int,
) -> dict[str, ynab.Category]:
    """Move a budgeted amount from one category to another for a month.

    YNAB has no atomic transfer endpoint: this reads both categories'
    current budgeted amounts, decrements the source, then increments the
    target. If the target update fails after the source was already
    decremented, a compensating call restores the source's original
    amount before raising.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id (translated to the SDK's ``plan_id``).
    month : str
        An ISO-formatted month (e.g. ``"2024-01-01"``) or ``"current"``.
    from_category_id : str
        The category to decrement.
    to_category_id : str
        The category to increment.
    amount : int
        The amount to move, in milliunits.

    Returns
    -------
    dict[str, ynab.Category]
        ``{"from_category": ..., "to_category": ...}``, the two updated
        categories.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If ``from_category_id`` equals ``to_category_id`` (reading the
        same category twice then writing it twice with a stale
        intermediate value would silently inflate its budgeted amount
        instead of leaving it unchanged), if ``month`` is invalid, if
        reading either category fails, or if the move itself fails. When
        the target update fails after the source was decremented, the
        error states whether the rollback succeeded or, if it also
        failed, exactly which category/month/amount is left inconsistent.
    """
    if from_category_id == to_category_id:
        raise ToolError("from_category_id and to_category_id must differ.")

    resolved_month = parse_month(month)
    api = ynab.CategoriesApi(client)
    try:
        from_current = call_with_retry(
            lambda: api.get_month_category_by_id(
                plan_id=budget_id, month=resolved_month, category_id=from_category_id
            )
        ).data.category.budgeted
        to_current = call_with_retry(
            lambda: api.get_month_category_by_id(
                plan_id=budget_id, month=resolved_month, category_id=to_category_id
            )
        ).data.category.budgeted
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc

    try:
        from_category = call_with_retry(
            lambda: api.update_month_category(
                plan_id=budget_id,
                month=resolved_month,
                category_id=from_category_id,
                data=ynab.PatchMonthCategoryWrapper(
                    category=ynab.SaveMonthCategory(budgeted=from_current - amount)
                ),
            )
        ).data.category
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc

    try:
        to_category = call_with_retry(
            lambda: api.update_month_category(
                plan_id=budget_id,
                month=resolved_month,
                category_id=to_category_id,
                data=ynab.PatchMonthCategoryWrapper(
                    category=ynab.SaveMonthCategory(budgeted=to_current + amount)
                ),
            )
        ).data.category
    except ynab.ApiException as exc:
        target_detail = str(translate_api_exception(exc))
        try:
            call_with_retry(
                lambda: api.update_month_category(
                    plan_id=budget_id,
                    month=resolved_month,
                    category_id=from_category_id,
                    data=ynab.PatchMonthCategoryWrapper(
                        category=ynab.SaveMonthCategory(budgeted=from_current)
                    ),
                )
            )
        except ynab.ApiException as rollback_exc:
            rollback_detail = str(translate_api_exception(rollback_exc))
            raise ToolError(
                f"Failed to move {amount} from {from_category_id} to "
                f"{to_category_id} for {month}: {target_detail}. Rollback of "
                f"the source category also failed ({rollback_detail}) -- "
                f"{from_category_id} is left decremented by {amount} for "
                f"{month} and needs manual correction."
            ) from rollback_exc
        raise ToolError(
            f"Failed to move {amount} from {from_category_id} to "
            f"{to_category_id} for {month}: {target_detail}. The source "
            "category was restored to its original budgeted amount."
        ) from exc

    return {"from_category": from_category, "to_category": to_category}


def register(mcp: FastMCP, client: ynab.ApiClient, settings: Settings) -> None:
    """Register the ``manage-budgeted-amount`` tool on ``mcp``.

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

    @mcp.tool(name="manage-budgeted-amount")
    async def manage_budgeted_amount_tool(
        operation: Literal["assign", "move"],
        month: str,
        ctx: Context,
        category_id: str | None = None,
        amount: int | None = None,
        from_category_id: str | None = None,
        to_category_id: str | None = None,
        budget_id: str | None = None,
    ) -> dict[str, object] | InputRequiredResult:
        """Assign or move a category's budgeted amount for a month.

        Parameters
        ----------
        operation : {"assign", "move"}
            Which operation to perform.
        month : str
            An ISO-formatted month (e.g. ``"2024-01-01"``) or ``"current"``.
        category_id : str | None, optional
            Required for ``"assign"``: the category to update.
        amount : int | None, optional
            Required for both operations: the amount in milliunits (the
            absolute amount for ``"assign"``, the amount to shift for
            ``"move"``).
        from_category_id : str | None, optional
            Required for ``"move"``: the category to decrement.
        to_category_id : str | None, optional
            Required for ``"move"``: the category to increment.
        budget_id : str | None, optional
            The YNAB budget id, by default ``None`` (falls back to
            ``YNAB_DEFAULT_BUDGET_ID``).
        """
        require_writable(settings)
        resolved_budget_id = resolve_budget_id(budget_id, settings)
        resolved_month = parse_month(month)
        arguments = {
            "operation": operation,
            "month": resolved_month,
            "category_id": category_id,
            "amount": amount,
            "from_category_id": from_category_id,
            "to_category_id": to_category_id,
        }
        if operation == "assign":
            if category_id is None or amount is None:
                raise ToolError("assign requires category_id and amount.")
            asked = await require_approval(
                ctx,
                settings,
                tool_name="manage-budgeted-amount",
                budget_id=resolved_budget_id,
                arguments=arguments,
                pending=pending_budget_assign(
                    client, resolved_budget_id, resolved_month, category_id, amount
                ),
            )
            if asked is not None:
                return asked
            category = await anyio.to_thread.run_sync(
                partial(
                    assign_budgeted_amount,
                    client,
                    resolved_budget_id,
                    resolved_month.isoformat(),
                    category_id,
                    amount,
                )
            )
            return category.model_dump(mode="json")

        if from_category_id is None or to_category_id is None or amount is None:
            raise ToolError(
                "move requires from_category_id, to_category_id, and amount."
            )
        if from_category_id == to_category_id:
            raise ToolError("from_category_id and to_category_id must differ.")
        asked = await require_approval(
            ctx,
            settings,
            tool_name="manage-budgeted-amount",
            budget_id=resolved_budget_id,
            arguments=arguments,
            pending=pending_budget_move(
                client,
                resolved_budget_id,
                resolved_month,
                from_category_id,
                to_category_id,
                amount,
            ),
        )
        if asked is not None:
            return asked
        result = await anyio.to_thread.run_sync(
            partial(
                move_budgeted_amount,
                client,
                resolved_budget_id,
                resolved_month.isoformat(),
                from_category_id,
                to_category_id,
                amount,
            )
        )
        return {
            "from_category": result["from_category"].model_dump(mode="json"),
            "to_category": result["to_category"].model_dump(mode="json"),
        }
