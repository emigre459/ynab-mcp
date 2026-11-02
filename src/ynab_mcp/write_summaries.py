"""Human-readable summaries of pending YNAB writes, for the approval prompt.

The prompt is plain text that also reads well if a client renders markdown:
line breaks and indented ``- Label:  value`` bullets, no tables or emphasis.
Every interpolated value goes through ``one_line``, so text an agent supplied
(a memo, a new payee name) can't forge lines of the prompt.
"""

import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import TypeVar

import ynab

from ynab_mcp.approval import ItemState, PendingWrite
from ynab_mcp.tools.accounts import list_accounts
from ynab_mcp.tools.budgets import list_budgets
from ynab_mcp.tools.categories import list_categories
from ynab_mcp.tools.payees import list_payees

T = TypeVar("T")

_FOOTER = "Nothing is written to YNAB unless you approve."
_CENT = Decimal("0.01")


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
