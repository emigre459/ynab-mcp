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
from enum import Enum
from typing import TypeVar

import ynab

from ynab_mcp.approval import ItemState, PendingWrite
from ynab_mcp.client import call_with_retry
from ynab_mcp.tools.accounts import list_accounts
from ynab_mcp.tools.budgets import list_budgets
from ynab_mcp.tools.categories import list_categories
from ynab_mcp.tools.payees import list_payees
from ynab_mcp.tools.transactions import list_transactions

T = TypeVar("T")

_FOOTER = "Nothing is written to YNAB unless you approve."
_CENT = Decimal("0.01")
_UNAVAILABLE = "(current values unavailable)"
_CLEARED = "(cleared)"
_NONE = "(none)"
_COMPARED_KEYS = {
    "Payee": "payee_id",
    "Category": "category_id",
    "Account": "account_id",
    "Amount": "amount",
}
# Above this many existing transactions, one list request replaces per-id reads:
# YNAB allows about 200 requests an hour, and a categorization pass can touch
# dozens of transactions, read twice each (at the prompt and at the re-check).
_BY_ID_LIMIT = 5


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
    current = names.payee(payee_id)
    lines = [f'  - "{current}"  →  "{one_line(new_name)}"']
    # YNAB merges payees when a rename lands on an existing name.
    for other_id, other_name in names.payees.items():
        if other_id != payee_id and other_name.casefold() == new_name.casefold():
            lines.append(
                f'  - "{one_line(other_name)}" already exists, so YNAB will merge '
                f'"{current}" into it. This can\'t be undone.'
            )
            break
    return _prompt(f'Rename payee in budget "{one_line(names.budget)}"?', lines)


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


def _plain(value: object) -> object:
    """Reduce an SDK field to a JSON-friendly value for state comparison."""
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, bool | int):
        return value
    return str(value)


def _is_unchanged(
    label: str,
    new: str | None,
    old: str | None,
    requested: Mapping[str, object],
    state: ItemState,
) -> bool:
    """Compare ids and raw amounts where possible: names can repeat or be missing."""
    key = _COMPARED_KEYS.get(label)
    if key is not None and requested.get(key) is not None:
        return str(requested[key]) == str(state.get(key))
    return new == old


def _field_lines(rows: list[tuple[str, str]]) -> list[str]:
    """Format label/value rows as aligned bullets."""
    width = max((len(label) for label, _ in rows), default=0) + 1
    return [f"  - {label + ':':<{width}}  {value}" for label, value in rows]


def _scheduled_targets(
    names: NameDirectory, fields: Mapping[str, object]
) -> list[tuple[str, str | None]]:
    """List a scheduled write's fields as requested; ``None`` means unset."""

    def text(value: object) -> str | None:
        return None if value is None else one_line(value)

    # YNAB only honors payee_name when payee_id is null.
    payee = (
        names.payee(fields["payee_id"])
        if fields.get("payee_id")
        else fields.get("payee_name")
    )
    category = fields.get("category_id")
    return [
        ("Date", text(fields.get("date"))),
        ("Frequency", text(fields.get("frequency"))),
        ("Payee", text(payee)),
        ("Amount", text(fields.get("amount"))),
        ("Category", names.category(category) if category else None),
        ("Account", names.account(fields.get("account_id"))),
        ("Memo", text(fields.get("memo"))),
        ("Flag", text(fields.get("flag_color"))),
    ]


def _scheduled_currents(state: ItemState) -> dict[str, str | None]:
    def text(key: str) -> str | None:
        value = state.get(key)
        return None if value is None else one_line(value)

    return {
        "Date": text("date"),
        "Frequency": text("frequency"),
        "Payee": text("payee_name"),
        "Amount": text("amount"),
        "Category": text("category_name"),
        "Account": text("account_name"),
        "Memo": text("memo"),
        "Flag": text("flag_color"),
    }


def _scheduled_identity(state: ItemState) -> str:
    payee = one_line(state.get("payee_name") or "(no payee)")
    return f"{payee}, {one_line(state['date'])}, {format_money(state['amount'])}"


def render_scheduled(
    names: NameDirectory,
    operation: str,
    scheduled_transaction_id: str | None,
    fields: Mapping[str, object],
    state: ItemState | None,
) -> str:
    """Build the prompt for a scheduled transaction write.

    Parameters
    ----------
    names : NameDirectory
        Display names.
    operation : str
        ``"create"``, ``"update"``, or ``"delete"``.
    scheduled_transaction_id : str | None
        The existing item, for ``"update"`` and ``"delete"``.
    fields : Mapping[str, object]
        The requested values.
    state : ItemState | None
        The existing item's current values, or ``None`` if unavailable.

    Returns
    -------
    str
        The prompt text. An update replaces the whole item, so a field left
        unset clears any existing value, and the prompt shows that.
    """
    in_budget = f'in budget "{one_line(names.budget)}"?'
    item_id = one_line(scheduled_transaction_id)
    if operation == "delete":
        if state is None:
            return _prompt(
                f"Delete scheduled transaction {item_id} {_UNAVAILABLE} {in_budget}",
                [],
            )
        return _prompt(
            f"Delete scheduled transaction {in_budget}",
            [
                f"  - {_scheduled_identity(state)}, {one_line(state['frequency'])}, "
                f"{one_line(state['account_name'])}"
            ],
        )

    def shown(label: str, value: str | None) -> str:
        if label == "Amount":
            return format_flow(fields.get("amount"))
        return value or ""

    targets = _scheduled_targets(names, fields)
    if operation == "create" or state is None:
        header = (
            f"Create scheduled transaction {in_budget}"
            if operation == "create"
            else f"Update scheduled transaction {item_id} {_UNAVAILABLE} {in_budget}"
        )
        rows = [(label, shown(label, value)) for label, value in targets if value]
        lines = _field_lines(rows)
        if operation == "update":
            lines.append("  - Any existing value for fields not listed is cleared")
        return _prompt(header, lines)

    currents = _scheduled_currents(state)
    rows = []
    for label, new in targets:
        old = currents[label]
        if _is_unchanged(label, new, old, fields, state):
            continue
        if label == "Amount":
            old_text = format_money(state["amount"])
            new_text = format_money(fields.get("amount"))
        else:
            old_text, new_text = old or _NONE, new or _CLEARED
        rows.append((label, f"{old_text}  →  {new_text}"))
    return _prompt(
        f"Update scheduled transaction ({_scheduled_identity(state)}) {in_budget}",
        _field_lines(rows),
    )


def pending_scheduled_write(
    client: ynab.ApiClient,
    budget_id: str,
    operation: str,
    scheduled_transaction_id: str | None,
    fields: Mapping[str, object],
) -> PendingWrite:
    """Describe a scheduled transaction write for approval.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id.
    operation : str
        ``"create"``, ``"update"``, or ``"delete"``.
    scheduled_transaction_id : str | None
        The existing item, for ``"update"`` and ``"delete"``.
    fields : Mapping[str, object]
        The requested values: ``account_id``, ``date``, ``amount``,
        ``frequency``, ``payee_id``, ``payee_name``, ``category_id``, ``memo``,
        ``flag_color``.

    Returns
    -------
    PendingWrite
        A pending write whose re-check covers the existing item, if any.
    """
    label = f"scheduled transaction {one_line(scheduled_transaction_id)}"

    def read_state() -> dict[str, ItemState | None]:
        if scheduled_transaction_id is None:
            return {}
        api = ynab.ScheduledTransactionsApi(client)
        try:
            item = call_with_retry(
                lambda: api.get_scheduled_transaction_by_id(
                    plan_id=budget_id,
                    scheduled_transaction_id=scheduled_transaction_id,
                )
            ).data.scheduled_transaction
        except Exception:
            return {label: None}
        return {
            label: {
                "date": _plain(item.date_first),
                "frequency": _plain(item.frequency),
                "amount": item.amount,
                "account_id": _plain(item.account_id),
                "account_name": item.account_name,
                "payee_id": _plain(item.payee_id),
                "payee_name": item.payee_name,
                "category_id": _plain(item.category_id),
                "category_name": item.category_name,
                "memo": item.memo,
                "flag_color": _plain(item.flag_color),
                "deleted": item.deleted,
            }
        }

    def render(states: Mapping[str, ItemState | None]) -> str:
        names = load_names(
            client,
            budget_id,
            categories=bool(fields.get("category_id")),
            accounts=operation != "delete",
            payees=bool(fields.get("payee_id")),
        )
        return render_scheduled(
            names, operation, scheduled_transaction_id, fields, states.get(label)
        )

    return PendingWrite(read_state=read_state, render=render)


def _yes_no(value: object) -> str:
    if value is True:
        return "yes"
    return "no" if value is False else one_line(value)


def _requested_rows(
    names: NameDirectory, operation: Mapping[str, object]
) -> list[tuple[str, str | None]]:
    """List an operation's requested values for display; ``None`` means unset."""

    def text(key: str, render: Callable[[object], str] = one_line) -> str | None:
        value = operation.get(key)
        return None if value is None else render(value)

    return [
        ("Date", text("date")),
        ("Payee", text("payee_id", names.payee) or text("payee_name")),
        ("Amount", text("amount", format_money)),
        ("Category", text("category_id", names.category)),
        ("Account", text("account_id", names.account)),
        ("Memo", text("memo")),
        ("Flag", text("flag_color")),
        ("Cleared", text("cleared")),
        ("Approved", text("approved", _yes_no)),
    ]


def _new_value_lines(
    names: NameDirectory, operation: Mapping[str, object]
) -> list[str]:
    rows = [
        (label, format_flow(operation.get("amount")) if label == "Amount" else value)
        for label, value in _requested_rows(names, operation)
        if value is not None
    ]
    return _field_lines(rows)


def _current_values(state: ItemState) -> dict[str, str | None]:
    def text(key: str, render: Callable[[object], str] = one_line) -> str | None:
        value = state.get(key)
        return None if value is None else render(value)

    return {
        "Date": text("date"),
        "Payee": text("payee_name"),
        "Amount": text("amount", format_money),
        "Category": text("category_name"),
        "Account": text("account_name"),
        "Memo": text("memo"),
        "Flag": text("flag_color"),
        "Cleared": text("cleared"),
        "Approved": text("approved", _yes_no),
    }


def _update_lines(
    names: NameDirectory, operation: Mapping[str, object], state: ItemState
) -> list[str]:
    currents = _current_values(state)
    rows: list[tuple[str, str]] = []
    for label, new in _requested_rows(names, operation):
        old = currents[label]
        if new is None:
            # Only an explicit flag_color null is sent (and clears the flag);
            # every other unset field stays untouched.
            if label == "Flag" and "flag_color" in operation and old is not None:
                rows.append((label, f"{old}  →  {_CLEARED}"))
        elif _is_unchanged(label, new, old, operation, state):
            rows.append((label, f"{old or new} (no change)"))
        else:
            rows.append((label, f"{old or _NONE}  →  {new}"))
    return _field_lines(rows)


def _transaction_identity(state: ItemState) -> str:
    payee = one_line(state.get("payee_name") or "(no payee)")
    return f"{payee}, {one_line(state['date'])}, {format_money(state['amount'])}"


def _operation_block(
    names: NameDirectory,
    operation: Mapping[str, object],
    states: Mapping[str, ItemState | None],
) -> list[str]:
    action = operation["action"]
    if action == "create":
        return ["Create transaction", *_new_value_lines(names, operation)]
    item_id = one_line(operation["id"])
    state = states.get(f"transaction {item_id}")
    if action == "delete":
        if state is None:
            return [f"Delete transaction {item_id} {_UNAVAILABLE}"]
        return [
            "Delete transaction",
            f"  - {_transaction_identity(state)}, {one_line(state['account_name'])}",
        ]
    if state is None:
        lines = [
            f"Update transaction {item_id} {_UNAVAILABLE}",
            *_new_value_lines(names, operation),
        ]
        if "flag_color" in operation and operation["flag_color"] is None:
            lines.append("  - Any existing flag is cleared")
        return lines
    return [
        f"Update transaction ({_transaction_identity(state)})",
        *_update_lines(names, operation, state),
    ]


def render_bulk(
    names: NameDirectory,
    operations: list[dict[str, object]],
    states: Mapping[str, ItemState | None],
) -> str:
    """Build the prompt for a bulk transaction write.

    Parameters
    ----------
    names : NameDirectory
        Display names.
    operations : list[dict[str, object]]
        The validated operations; every one is listed, with no truncation.
    states : Mapping[str, ItemState | None]
        Existing transactions' current values, by item label.

    Returns
    -------
    str
        The prompt text.
    """
    count = len(operations)
    noun = "change" if count == 1 else "changes"
    lines: list[str] = []
    for operation in operations:
        if lines:
            lines.append("")
        lines.extend(_operation_block(names, operation, states))
    return _prompt(f'Apply {count} {noun} to budget "{one_line(names.budget)}"?', lines)


def _transaction_state(transaction: ynab.TransactionDetail) -> ItemState:
    return {
        "date": _plain(transaction.var_date),
        "amount": transaction.amount,
        "payee_id": _plain(transaction.payee_id),
        "payee_name": transaction.payee_name,
        "category_id": _plain(transaction.category_id),
        "category_name": transaction.category_name,
        "account_id": _plain(transaction.account_id),
        "account_name": transaction.account_name,
        "memo": transaction.memo,
        "cleared": _plain(transaction.cleared),
        "approved": transaction.approved,
        "flag_color": _plain(transaction.flag_color),
        "deleted": transaction.deleted,
    }


def _read_transactions(
    client: ynab.ApiClient, budget_id: str, transaction_ids: list[str]
) -> dict[str, ItemState | None]:
    """Read existing transactions: per id when few, one list request when many."""
    if len(transaction_ids) > _BY_ID_LIMIT:
        found = {
            str(transaction.id): _transaction_state(transaction)
            for transaction in list_transactions(client, budget_id)
        }
        return {f"transaction {i}": found.get(i) for i in transaction_ids}

    api = ynab.TransactionsApi(client)
    states: dict[str, ItemState | None] = {}
    for transaction_id in transaction_ids:
        try:
            transaction = call_with_retry(
                lambda: api.get_transaction_by_id(
                    plan_id=budget_id, transaction_id=transaction_id
                )
            ).data.transaction
        except Exception:
            states[f"transaction {transaction_id}"] = None
        else:
            states[f"transaction {transaction_id}"] = _transaction_state(transaction)
    return states


def pending_transactions_write(
    client: ynab.ApiClient, budget_id: str, operations: list[dict[str, object]]
) -> PendingWrite:
    """Describe a bulk transaction write for approval.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id.
    operations : list[dict[str, object]]
        The validated operations.

    Returns
    -------
    PendingWrite
        A pending write whose re-check covers every transaction being updated
        or deleted.
    """
    existing_ids = list(
        dict.fromkeys(
            one_line(operation["id"])
            for operation in operations
            if operation["action"] in ("update", "delete")
        )
    )

    def wants(key: str) -> bool:
        return any(operation.get(key) for operation in operations)

    def render(states: Mapping[str, ItemState | None]) -> str:
        names = load_names(
            client,
            budget_id,
            categories=wants("category_id"),
            accounts=wants("account_id"),
            payees=wants("payee_id"),
        )
        return render_bulk(names, operations, states)

    return PendingWrite(
        read_state=lambda: (
            _read_transactions(client, budget_id, existing_ids) if existing_ids else {}
        ),
        render=render,
    )
