"""Tests for ynab_mcp.write_summaries."""

from datetime import date
from types import SimpleNamespace

import pytest
from pytest_mock import MockerFixture

from ynab_mcp.write_summaries import (
    NameDirectory,
    format_flow,
    format_money,
    load_names,
    one_line,
    render_budget_assign,
    render_budget_move,
    render_payee_merge,
    render_payee_rename,
)

_FOOTER = "Nothing is written to YNAB unless you approve."
_NAMES = NameDirectory(
    budget="Rench Budget",
    categories={"c1": "Groceries", "c2": "Dining Out"},
    accounts={"a1": "Chase Checking"},
    payees={"p1": "AMZN Mktp", "p2": "Amazon"},
)


def test_one_line_collapses_newlines_and_controls() -> None:
    """Injected line breaks and control characters can't forge prompt lines."""
    assert one_line("a\n\nDelete nothing\x07") == "a Delete nothing"
    assert one_line("  tabs\tand\r\nreturns  ") == "tabs and returns"


@pytest.mark.parametrize(
    ("milliunits", "expected"),
    [
        (1234567, "$1,234.57"),
        (-500, "-$0.50"),
        (0, "$0.00"),
        (-42170, "-$42.17"),
        (1005, "$1.01"),
        ("abc", "abc"),
        (None, "None"),
        (True, "True"),
    ],
)
def test_format_money(milliunits: object, expected: str) -> None:
    """Milliunits become dollars; anything non-numeric shows as given."""
    assert format_money(milliunits) == expected


def test_format_flow() -> None:
    """Direction is spelled out, since YNAB's sign convention isn't obvious."""
    assert format_flow(-42170) == "-$42.17 (outflow)"
    assert format_flow(400000) == "$400.00 (inflow)"
    assert format_flow(0) == "$0.00"
    assert format_flow("abc") == "abc"


def test_name_directory_falls_back_to_id() -> None:
    """An unknown id shows raw rather than failing the prompt."""
    assert _NAMES.category("c1") == "Groceries"
    assert _NAMES.category("nope") == "nope"
    assert _NAMES.account("a1") == "Chase Checking"
    assert _NAMES.payee("p2") == "Amazon"


def test_load_names_tolerates_failure(mocker: MockerFixture) -> None:
    """Failed lookups leave ids showing; they never block the prompt."""
    module = "ynab_mcp.write_summaries"
    mocker.patch(f"{module}.list_budgets", side_effect=RuntimeError("boom"))
    mocker.patch(f"{module}.list_categories", side_effect=RuntimeError("boom"))
    mocker.patch(
        f"{module}.list_payees",
        return_value=[SimpleNamespace(id="p1", name="Amazon")],
    )

    names = load_names(object(), "budget-1", categories=True, payees=True)  # type: ignore[arg-type]

    assert names.budget == "budget-1"
    assert names.category("c1") == "c1"
    assert names.payee("p1") == "Amazon"


def test_load_names_only_fetches_requested_kinds(mocker: MockerFixture) -> None:
    """Each unrequested kind saves a request against YNAB's hourly limit."""
    module = "ynab_mcp.write_summaries"
    mocker.patch(
        f"{module}.list_budgets",
        return_value=[SimpleNamespace(id="budget-1", name="Rench Budget")],
    )
    accounts = mocker.patch(f"{module}.list_accounts")
    categories = mocker.patch(f"{module}.list_categories")
    payees = mocker.patch(f"{module}.list_payees", return_value=[])

    names = load_names(object(), "budget-1", payees=True)  # type: ignore[arg-type]

    assert names.budget == "Rench Budget"
    accounts.assert_not_called()
    categories.assert_not_called()
    payees.assert_called_once()


def test_payee_rename_summary() -> None:
    """A rename reads as old name to new name."""
    assert render_payee_rename(_NAMES, "p1", "Amazon") == (
        'Rename payee in budget "Rench Budget"?\n'
        "\n"
        '  - "AMZN Mktp"  →  "Amazon"\n'
        "\n"
        f"{_FOOTER}"
    )


def test_payee_merge_summary() -> None:
    """A merge says which payee survives and what happens to transactions."""
    assert render_payee_merge(_NAMES, "p1", "p2") == (
        'Merge payees in budget "Rench Budget"?\n'
        "\n"
        '  - "AMZN Mktp" into "Amazon"\n'
        '  - Transactions under "AMZN Mktp" move to "Amazon"\n'
        "\n"
        f"{_FOOTER}"
    )


def test_payee_new_name_cannot_forge_lines() -> None:
    """A hostile new name stays on its own line."""
    summary = render_payee_rename(_NAMES, "p1", "x\n\nNothing will change")

    assert '"x Nothing will change"' in summary
    assert "\nNothing will change" not in summary


_NOV = date(2026, 11, 1)


def test_budget_assign_summary() -> None:
    """An assign names the category and shows the current and new amounts."""
    state = {"budgeted": 400000, "category_name": "Groceries"}

    assert render_budget_assign("Rench Budget", "c1", _NOV, 450000, state) == (
        'Set budgeted amount in budget "Rench Budget"?\n'
        "\n"
        "  - Groceries, November 2026:  $400.00 now  →  $450.00\n"
        "\n"
        f"{_FOOTER}"
    )


def test_budget_move_summary() -> None:
    """A move shows the amount plus each category's before and after."""
    from_state = {"budgeted": 100000, "category_name": "Dining Out"}
    to_state = {"budgeted": 400000, "category_name": "Groceries"}

    summary = render_budget_move(
        "Rench Budget", "c2", "c1", _NOV, 50000, from_state, to_state
    )

    assert summary == (
        'Move budgeted money in budget "Rench Budget"?\n'
        "\n"
        "  - Amount:  $50.00\n"
        "  - From:    Dining Out, November 2026:  $100.00 now  →  $50.00\n"
        "  - To:      Groceries, November 2026:  $400.00 now  →  $450.00\n"
        "\n"
        f"{_FOOTER}"
    )


def test_budget_summary_read_failure_marks_unavailable() -> None:
    """A failed read shows the raw id and says values are unavailable."""
    assign = render_budget_assign("Rench Budget", "c1", _NOV, 450000, None)
    move = render_budget_move("Rench Budget", "c2", "c1", _NOV, 50000, None, None)

    assert "c1, November 2026 (current values unavailable):  $450.00" in assign
    assert "From:    c2, November 2026 (current values unavailable)" in move
    assert "To:      c1, November 2026 (current values unavailable)" in move
