"""Human-readable summaries of pending YNAB writes, for the approval prompt.

The prompt is plain text that also reads well if a client renders markdown:
line breaks and indented ``- Label:  value`` bullets, no tables or emphasis.
Every interpolated value goes through ``one_line``, so text an agent supplied
(a memo, a new payee name) can't forge lines of the prompt.
"""

import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import TypeVar

import ynab

from ynab_mcp.approval import ItemState, PendingWrite
from ynab_mcp.client import call_with_retry
from ynab_mcp.tools.accounts import list_accounts
from ynab_mcp.tools.budgets import list_budgets
from ynab_mcp.tools.categories import list_categories
from ynab_mcp.tools.payees import list_payees

T = TypeVar("T")

_FOOTER = "Nothing is written to YNAB unless you approve."
_CENT = Decimal("0.01")
_UNAVAILABLE = "(current values unavailable)"


def one_line(value: object) -> str:
    """Render a value on a single line, dropping controls and line breaks.

    Parameters
    ----------
    value : object
        Anything to show in the prompt.

    Returns
    -------
    str
        The value's text with control, format, and line/paragraph separator
        characters replaced by spaces and whitespace runs collapsed.
    """
    text = "".join(
        " " if unicodedata.category(char)[0] == "C" or char in "  " else char
        for char in str(value)
    )
    return " ".join(text.split())


def format_money(milliunits: object) -> str:
    """Format a YNAB milliunit amount as dollars.

    Parameters
    ----------
    milliunits : object
        The amount, in milliunits. Operation dicts are unvalidated until the
        write itself, so this may be anything.

    Returns
    -------
    str
        For example ``"$1,234.57"`` or ``"-$0.50"``; a value that isn't an
        integer is shown as given.
    """
    if not isinstance(milliunits, int) or isinstance(milliunits, bool):
        return one_line(milliunits)
    dollars = (Decimal(milliunits) / 1000).quantize(_CENT, rounding=ROUND_HALF_UP)
    sign = "-" if dollars < 0 else ""
    return f"{sign}${abs(dollars):,.2f}"


def format_flow(milliunits: object) -> str:
    """Format a transaction amount with its direction spelled out.

    Parameters
    ----------
    milliunits : object
        The amount, in milliunits; negative is money leaving the account.

    Returns
    -------
    str
        For example ``"-$42.17 (outflow)"`` or ``"$400.00 (inflow)"``.
    """
    money = format_money(milliunits)
    if not isinstance(milliunits, int) or isinstance(milliunits, bool):
        return money
    if milliunits < 0:
        return f"{money} (outflow)"
    if milliunits > 0:
        return f"{money} (inflow)"
    return money


@dataclass(frozen=True)
class NameDirectory:
    """Display names by YNAB id; an unknown id shows as itself.

    Parameters
    ----------
    budget : str
        The budget's name, or its id if the lookup failed.
    categories : Mapping[str, str]
        Category names by id.
    accounts : Mapping[str, str]
        Account names by id.
    payees : Mapping[str, str]
        Payee names by id.
    """

    budget: str
    categories: Mapping[str, str] = field(default_factory=dict)
    accounts: Mapping[str, str] = field(default_factory=dict)
    payees: Mapping[str, str] = field(default_factory=dict)

    def category(self, category_id: object) -> str:
        """Return a category's display name."""
        return one_line(self.categories.get(str(category_id), category_id))

    def account(self, account_id: object) -> str:
        """Return an account's display name."""
        return one_line(self.accounts.get(str(account_id), account_id))

    def payee(self, payee_id: object) -> str:
        """Return a payee's display name."""
        return one_line(self.payees.get(str(payee_id), payee_id))


def _names_by_id(fetch: Callable[[], list[T]]) -> dict[str, str]:
    """Map id to name, treating any failure as no names: the prompt shows ids."""
    try:
        return {str(item.id): item.name for item in fetch()}  # type: ignore[attr-defined]
    except Exception:
        return {}


def load_names(
    client: ynab.ApiClient,
    budget_id: str,
    *,
    categories: bool = False,
    accounts: bool = False,
    payees: bool = False,
) -> NameDirectory:
    """Fetch display names for a prompt, one list request per requested kind.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id.
    categories : bool, optional
        Whether to fetch category names, by default ``False``.
    accounts : bool, optional
        Whether to fetch account names, by default ``False``.
    payees : bool, optional
        Whether to fetch payee names, by default ``False``.

    Returns
    -------
    NameDirectory
        The names found. A failed lookup never raises: that kind's ids simply
        show raw in the prompt.
    """
    budget_names = _names_by_id(lambda: list_budgets(client))
    return NameDirectory(
        budget=budget_names.get(budget_id, budget_id),
        categories=(
            _names_by_id(lambda: list_categories(client, budget_id))
            if categories
            else {}
        ),
        accounts=(
            _names_by_id(lambda: list_accounts(client, budget_id)) if accounts else {}
        ),
        payees=_names_by_id(lambda: list_payees(client, budget_id)) if payees else {},
    )


def _prompt(header: str, lines: list[str]) -> str:
    return "\n".join([header, "", *lines, "", _FOOTER])


def render_payee_rename(names: NameDirectory, payee_id: str, new_name: str) -> str:
    """Build the prompt for renaming a payee.

    Parameters
    ----------
    names : NameDirectory
        Display names.
    payee_id : str
        The payee being renamed.
    new_name : str
        The payee's new name.

    Returns
    -------
    str
        The prompt text.
    """
    return _prompt(
        f'Rename payee in budget "{one_line(names.budget)}"?',
        [f'  - "{names.payee(payee_id)}"  →  "{one_line(new_name)}"'],
    )


def render_payee_merge(names: NameDirectory, source_id: str, target_id: str) -> str:
    """Build the prompt for merging one payee into another.

    Parameters
    ----------
    names : NameDirectory
        Display names.
    source_id : str
        The payee being merged away.
    target_id : str
        The payee that survives.

    Returns
    -------
    str
        The prompt text.
    """
    source, target = names.payee(source_id), names.payee(target_id)
    return _prompt(
        f'Merge payees in budget "{one_line(names.budget)}"?',
        [
            f'  - "{source}" into "{target}"',
            f'  - Transactions under "{source}" move to "{target}"',
        ],
    )


def pending_payee_rename(
    client: ynab.ApiClient, budget_id: str, payee_id: str, new_name: str
) -> PendingWrite:
    """Describe a payee rename for approval.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id.
    payee_id : str
        The payee being renamed.
    new_name : str
        The payee's new name.

    Returns
    -------
    PendingWrite
        A pending write with no state to re-check: a rename depends on no
        current value.
    """

    def render(_: Mapping[str, ItemState | None]) -> str:
        names = load_names(client, budget_id, payees=True)
        return render_payee_rename(names, payee_id, new_name)

    return PendingWrite(read_state=dict, render=render)


def pending_payee_merge(
    client: ynab.ApiClient, budget_id: str, source_id: str, target_id: str
) -> PendingWrite:
    """Describe a payee merge for approval.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id.
    source_id : str
        The payee being merged away.
    target_id : str
        The payee that survives.

    Returns
    -------
    PendingWrite
        A pending write with no state to re-check: the merge itself errors
        if either payee no longer exists.
    """

    def render(_: Mapping[str, ItemState | None]) -> str:
        names = load_names(client, budget_id, payees=True)
        return render_payee_merge(names, source_id, target_id)

    return PendingWrite(read_state=dict, render=render)


def _budget_change_line(
    category_id: str, month: date, state: ItemState | None, change: int, *, delta: bool
) -> str:
    """Describe one category's budgeted change, or that it couldn't be read."""
    when = month.strftime("%B %Y")
    if state is None:
        return f"{one_line(category_id)}, {when} {_UNAVAILABLE}"
    budgeted = state["budgeted"]
    after = budgeted + change if delta and isinstance(budgeted, int) else change
    return (
        f"{one_line(state['category_name'])}, {when}:  "
        f"{format_money(budgeted)} now  →  {format_money(after)}"
    )


def render_budget_assign(
    budget_name: str,
    category_id: str,
    month: date,
    amount: int,
    state: ItemState | None,
) -> str:
    """Build the prompt for setting a category's budgeted amount.

    Parameters
    ----------
    budget_name : str
        The budget's display name.
    category_id : str
        The category being set, shown raw if its read failed.
    month : datetime.date
        The month being budgeted.
    amount : int
        The new budgeted amount, in milliunits.
    state : ItemState | None
        The category's current values, or ``None`` if the read failed.

    Returns
    -------
    str
        The prompt text.
    """
    line = _budget_change_line(category_id, month, state, amount, delta=False)
    if state is None:
        line = f"{line}:  {format_money(amount)}"
    return _prompt(
        f'Set budgeted amount in budget "{one_line(budget_name)}"?', [f"  - {line}"]
    )


def render_budget_move(
    budget_name: str,
    from_category_id: str,
    to_category_id: str,
    month: date,
    amount: int,
    from_state: ItemState | None,
    to_state: ItemState | None,
) -> str:
    """Build the prompt for moving budgeted money between categories.

    Parameters
    ----------
    budget_name : str
        The budget's display name.
    from_category_id : str
        The category losing money, shown raw if its read failed.
    to_category_id : str
        The category gaining money, shown raw if its read failed.
    month : datetime.date
        The month being budgeted.
    amount : int
        The amount to move, in milliunits.
    from_state : ItemState | None
        The source's current values, or ``None`` if the read failed.
    to_state : ItemState | None
        The target's current values, or ``None`` if the read failed.

    Returns
    -------
    str
        The prompt text.
    """
    source = _budget_change_line(
        from_category_id, month, from_state, -amount, delta=True
    )
    target = _budget_change_line(to_category_id, month, to_state, amount, delta=True)
    return _prompt(
        f'Move budgeted money in budget "{one_line(budget_name)}"?',
        [
            f"  - Amount:  {format_money(amount)}",
            f"  - From:    {source}",
            f"  - To:      {target}",
        ],
    )


def _category_label(category_id: str, month: date) -> str:
    return f"category {one_line(category_id)} ({month:%Y-%m})"


def _read_month_categories(
    client: ynab.ApiClient, budget_id: str, month: date, category_ids: list[str]
) -> dict[str, ItemState | None]:
    """Read each category's current budgeted amount; a failure marks that item."""
    api = ynab.CategoriesApi(client)
    states: dict[str, ItemState | None] = {}
    for category_id in category_ids:
        label = _category_label(category_id, month)
        try:
            category = call_with_retry(
                lambda: api.get_month_category_by_id(
                    plan_id=budget_id, month=month, category_id=category_id
                )
            ).data.category
        except Exception:
            states[label] = None
        else:
            states[label] = {
                "budgeted": category.budgeted,
                "category_name": category.name,
            }
    return states


def pending_budget_assign(
    client: ynab.ApiClient, budget_id: str, month: date, category_id: str, amount: int
) -> PendingWrite:
    """Describe setting a category's budgeted amount for approval.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id.
    month : datetime.date
        The month being budgeted.
    category_id : str
        The category being set.
    amount : int
        The new budgeted amount, in milliunits.

    Returns
    -------
    PendingWrite
        A pending write whose re-check covers the category's budgeted amount.
    """

    def render(states: Mapping[str, ItemState | None]) -> str:
        names = load_names(client, budget_id)
        state = states.get(_category_label(category_id, month))
        return render_budget_assign(names.budget, category_id, month, amount, state)

    return PendingWrite(
        read_state=lambda: _read_month_categories(
            client, budget_id, month, [category_id]
        ),
        render=render,
    )


def pending_budget_move(
    client: ynab.ApiClient,
    budget_id: str,
    month: date,
    from_category_id: str,
    to_category_id: str,
    amount: int,
) -> PendingWrite:
    """Describe moving budgeted money between categories for approval.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id.
    month : datetime.date
        The month being budgeted.
    from_category_id : str
        The category losing money.
    to_category_id : str
        The category gaining money.
    amount : int
        The amount to move, in milliunits.

    Returns
    -------
    PendingWrite
        A pending write whose re-check covers both budgeted amounts: a move is
        relative, so a changed total would land somewhere other than shown.
    """

    def render(states: Mapping[str, ItemState | None]) -> str:
        names = load_names(client, budget_id)
        return render_budget_move(
            names.budget,
            from_category_id,
            to_category_id,
            month,
            amount,
            states.get(_category_label(from_category_id, month)),
            states.get(_category_label(to_category_id, month)),
        )

    return PendingWrite(
        read_state=lambda: _read_month_categories(
            client, budget_id, month, [from_category_id, to_category_id]
        ),
        render=render,
    )
