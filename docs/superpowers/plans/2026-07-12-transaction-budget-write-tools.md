# Transaction & Budget Write Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four MCP write tools (`bulk-manage-transactions`, `manage-budgeted-amount`, `manage-payees`, `manage-scheduled-transaction`) gated by `YNAB_READ_ONLY`, per issue #12.

**Architecture:** Four new modules in `src/ynab_mcp/tools/`, each following the existing plain-function + `register(mcp, client, settings)` pattern. A new shared `require_writable(settings)` guard in `client.py`, called as the first statement inside each write tool's registered closure. All four tools are registered unconditionally in `server.py` (always discoverable; the guard blocks execution, not discovery).

**Tech Stack:** Python 3.13, `fastmcp` v3, official `ynab` SDK v4 (`ynab.TransactionsApi`, `ynab.CategoriesApi`, `ynab.PayeesApi`, `ynab.ScheduledTransactionsApi`), `pytest` + `pytest-mock`.

**Spec:** `docs/superpowers/specs/2026-07-12-transaction-budget-write-tools-design.md`

## Global Constraints

- Python `>=3.13.5,<3.14`; every function has full type hints (`mypy` runs with `disallow_untyped_defs = true`).
- Formatting: `black` (line length 88); `ruff` with `extend-select = ["E501", "W", "D"]` and numpy-convention docstrings (`[tool.ruff.lint.pydocstyle] convention = "numpy"`) on every module/function/public-class.
- Every new/changed module must pass `make lint` (black --check + ruff + mypy) and `make tests` (pytest, excludes e2e/integration).
- Follow the existing `tools/` module pattern exactly: a plain, testable function per operation, plus a thin `register(mcp, client, settings)` that wraps it in an `@mcp.tool`-decorated closure. `ynab.ApiException` is always translated via `ynab_mcp.errors.translate_api_exception`.
- Test style: mock the relevant `ynab.*Api` class via `mocker.patch("ynab_mcp.tools.<module>.ynab.<ApiClass>")`, assert call kwargs, assert `ApiException` -> `ToolError`. See `tests/test_tools_payees.py` / `tests/test_tools_months.py` for the exact reference pattern.
- `amount` fields are YNAB milliunits (int); `budgeted` fields on `ynab.Category` are also milliunits (int).
- Money-affecting code (bulk transactions, budgeted-amount moves) never silently swallows partial failure — every partial-failure path returns or raises a message naming the exact inconsistent state.

---

### Task 1: `require_writable` read-only guard

**Files:**
- Modify: `src/ynab_mcp/client.py`
- Test: `tests/test_client.py`

**Interfaces:**
- Produces: `require_writable(settings: Settings) -> None`, raising `fastmcp.exceptions.ToolError` when `settings.ynab_read_only` is `True`, otherwise returning `None`. Every later task's `register()` closure calls this as its first statement.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_client.py` (update the import line and append two tests):

```python
"""Tests for ynab_mcp.client."""

import pytest
from fastmcp.exceptions import ToolError

from ynab_mcp.client import build_api_client, require_writable, resolve_budget_id
from ynab_mcp.config import Settings


def test_build_api_client_uses_pat_as_access_token() -> None:
    """The configured YNAB_PAT is used as the SDK's access token."""
    settings = Settings(
        ynab_pat="test-token", ynab_default_budget_id=None, ynab_read_only=True
    )

    client = build_api_client(settings)

    assert client.configuration.access_token == "test-token"


def test_resolve_budget_id_prefers_explicit_value() -> None:
    """An explicitly passed budget_id wins over the configured default."""
    settings = Settings(
        ynab_pat="x", ynab_default_budget_id="default-budget", ynab_read_only=True
    )

    assert resolve_budget_id("explicit-budget", settings) == "explicit-budget"


def test_resolve_budget_id_falls_back_to_default() -> None:
    """Omitting budget_id falls back to YNAB_DEFAULT_BUDGET_ID."""
    settings = Settings(
        ynab_pat="x", ynab_default_budget_id="default-budget", ynab_read_only=True
    )

    assert resolve_budget_id(None, settings) == "default-budget"


def test_resolve_budget_id_raises_when_neither_present() -> None:
    """No explicit budget_id and no default configured is an error."""
    settings = Settings(ynab_pat="x", ynab_default_budget_id=None, ynab_read_only=True)

    with pytest.raises(ToolError, match="budget_id"):
        resolve_budget_id(None, settings)


def test_require_writable_raises_when_read_only() -> None:
    """A read-only configuration blocks the call with a clear ToolError."""
    settings = Settings(ynab_pat="x", ynab_default_budget_id=None, ynab_read_only=True)

    with pytest.raises(ToolError, match="YNAB_READ_ONLY"):
        require_writable(settings)


def test_require_writable_passes_when_writable() -> None:
    """A writable configuration does not raise."""
    settings = Settings(
        ynab_pat="x", ynab_default_budget_id=None, ynab_read_only=False
    )

    require_writable(settings)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_client.py -v --tb=short`
Expected: FAIL — `ImportError: cannot import name 'require_writable'`.

- [ ] **Step 3: Implement `require_writable`**

In `src/ynab_mcp/client.py`, add the new function (after `resolve_budget_id`):

```python
def require_writable(settings: Settings) -> None:
    """Guard a write tool against ``YNAB_READ_ONLY``.

    Parameters
    ----------
    settings : Settings
        The server's parsed configuration.

    Raises
    ------
    ToolError
        If ``settings.ynab_read_only`` is ``True``.
    """
    if settings.ynab_read_only:
        raise ToolError("YNAB_READ_ONLY is enabled; write operations are disabled.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_client.py -v --tb=short`
Expected: PASS (6 tests).

- [ ] **Step 5: Lint and commit**

```bash
uv run black src/ynab_mcp/client.py tests/test_client.py
uv run ruff check src/ynab_mcp/client.py tests/test_client.py
uv run mypy
git add src/ynab_mcp/client.py tests/test_client.py
git commit -m "feat: add require_writable read-only guard"
git push
```

---

### Task 2: `manage-payees` tool (rename + merge)

**Files:**
- Create: `src/ynab_mcp/tools/payees_write.py`
- Test: `tests/test_tools_payees_write.py`

**Interfaces:**
- Consumes: `require_writable(settings)` and `resolve_budget_id(budget_id, settings)` from Task 1 / existing `client.py`; `translate_api_exception(exc)` from `errors.py`.
- Produces: `rename_payee(client, budget_id, payee_id, new_name) -> ynab.Payee`; `merge_payees(client, budget_id, source_payee_id, target_payee_id) -> ynab.Payee`; `register(mcp, client, settings) -> None` registering the `manage-payees` tool.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tools_payees_write.py`:

```python
"""Tests for ynab_mcp.tools.payees_write."""

from types import SimpleNamespace

import ynab
from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

from ynab_mcp.tools.payees_write import merge_payees, rename_payee


def test_rename_payee_calls_update_payee(mocker: MockerFixture) -> None:
    """rename_payee calls PayeesApi.update_payee with the new name."""
    client = mocker.Mock()
    payees_api = mocker.patch("ynab_mcp.tools.payees_write.ynab.PayeesApi")
    fake_payee = SimpleNamespace(id="p1", name="Amazon")
    payees_api.return_value.update_payee.return_value = SimpleNamespace(
        data=SimpleNamespace(payee=fake_payee)
    )

    result = rename_payee(client, "budget-1", "p1", "Amazon")

    assert result == fake_payee
    call = payees_api.return_value.update_payee.call_args
    assert call.kwargs["plan_id"] == "budget-1"
    assert call.kwargs["payee_id"] == "p1"
    assert call.kwargs["data"].payee.name == "Amazon"


def test_rename_payee_raises_tool_error_on_api_exception(
    mocker: MockerFixture,
) -> None:
    """An ApiException from the SDK surfaces as a ToolError."""
    client = mocker.Mock()
    payees_api = mocker.patch("ynab_mcp.tools.payees_write.ynab.PayeesApi")
    payees_api.return_value.update_payee.side_effect = ynab.ApiException(
        status=404,
        reason="Not Found",
        body='{"error": {"id": "404", "name": "not_found", '
        '"detail": "Payee not found"}}',
    )

    with raises(ToolError, match="Payee not found"):
        rename_payee(client, "budget-1", "missing-payee", "Amazon")


def test_merge_payees_renames_source_to_target_name(mocker: MockerFixture) -> None:
    """merge_payees reads the target's name and renames the source to match."""
    client = mocker.Mock()
    payees_api = mocker.patch("ynab_mcp.tools.payees_write.ynab.PayeesApi")
    target_payee = SimpleNamespace(id="p2", name="Amazon.com")
    merged_payee = SimpleNamespace(id="p1", name="Amazon.com")
    payees_api.return_value.get_payee_by_id.return_value = SimpleNamespace(
        data=SimpleNamespace(payee=target_payee)
    )
    payees_api.return_value.update_payee.return_value = SimpleNamespace(
        data=SimpleNamespace(payee=merged_payee)
    )

    result = merge_payees(client, "budget-1", "p1", "p2")

    assert result == merged_payee
    payees_api.return_value.get_payee_by_id.assert_called_once_with(
        plan_id="budget-1", payee_id="p2"
    )
    update_call = payees_api.return_value.update_payee.call_args
    assert update_call.kwargs["plan_id"] == "budget-1"
    assert update_call.kwargs["payee_id"] == "p1"
    assert update_call.kwargs["data"].payee.name == "Amazon.com"


def test_merge_payees_raises_tool_error_on_api_exception(
    mocker: MockerFixture,
) -> None:
    """An ApiException from the SDK surfaces as a ToolError."""
    client = mocker.Mock()
    payees_api = mocker.patch("ynab_mcp.tools.payees_write.ynab.PayeesApi")
    payees_api.return_value.get_payee_by_id.side_effect = ynab.ApiException(
        status=404,
        reason="Not Found",
        body='{"error": {"id": "404", "name": "not_found", '
        '"detail": "Payee not found"}}',
    )

    with raises(ToolError, match="Payee not found"):
        merge_payees(client, "budget-1", "p1", "missing-payee")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_payees_write.py -v --tb=short`
Expected: FAIL — `ModuleNotFoundError: No module named 'ynab_mcp.tools.payees_write'`.

- [ ] **Step 3: Implement `payees_write.py`**

Create `src/ynab_mcp/tools/payees_write.py`:

```python
"""manage-payees tool: rename or merge payees."""

from typing import Literal

import ynab
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from ynab_mcp.client import require_writable, resolve_budget_id
from ynab_mcp.config import Settings
from ynab_mcp.errors import translate_api_exception


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
        response = api.update_payee(
            plan_id=budget_id,
            payee_id=payee_id,
            data=ynab.PatchPayeeWrapper(payee=ynab.SavePayee(name=new_name)),
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
        target = api.get_payee_by_id(plan_id=budget_id, payee_id=target_payee_id)
        response = api.update_payee(
            plan_id=budget_id,
            payee_id=source_payee_id,
            data=ynab.PatchPayeeWrapper(
                payee=ynab.SavePayee(name=target.data.payee.name)
            ),
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
    def manage_payees_tool(
        operation: Literal["rename", "merge"],
        payee_id: str | None = None,
        new_name: str | None = None,
        source_payee_id: str | None = None,
        target_payee_id: str | None = None,
        budget_id: str | None = None,
    ) -> dict[str, object]:
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
        if operation == "rename":
            if payee_id is None or new_name is None:
                raise ToolError("rename requires payee_id and new_name.")
            payee = rename_payee(client, resolved_budget_id, payee_id, new_name)
        else:
            if source_payee_id is None or target_payee_id is None:
                raise ToolError(
                    "merge requires source_payee_id and target_payee_id."
                )
            payee = merge_payees(
                client, resolved_budget_id, source_payee_id, target_payee_id
            )
        return payee.model_dump(mode="json")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_payees_write.py -v --tb=short`
Expected: PASS (4 tests).

- [ ] **Step 5: Lint and commit**

```bash
uv run black src/ynab_mcp/tools/payees_write.py tests/test_tools_payees_write.py
uv run ruff check src/ynab_mcp/tools/payees_write.py tests/test_tools_payees_write.py
uv run mypy
git add src/ynab_mcp/tools/payees_write.py tests/test_tools_payees_write.py
git commit -m "feat: add manage-payees tool (rename + merge)"
git push
```

---

### Task 3: `manage-scheduled-transaction` tool

**Files:**
- Create: `src/ynab_mcp/tools/scheduled_transactions.py`
- Test: `tests/test_tools_scheduled_transactions.py`

**Interfaces:**
- Consumes: `require_writable`, `resolve_budget_id`, `translate_api_exception` (same as Task 2).
- Produces: `create_scheduled_transaction(client, budget_id, account_id, date, amount, frequency, *, payee_id=None, payee_name=None, category_id=None, memo=None, flag_color=None) -> ynab.ScheduledTransactionDetail`; `update_scheduled_transaction(client, budget_id, scheduled_transaction_id, account_id, date, amount, frequency, *, payee_id=None, payee_name=None, category_id=None, memo=None, flag_color=None) -> ynab.ScheduledTransactionDetail`; `delete_scheduled_transaction(client, budget_id, scheduled_transaction_id) -> ynab.ScheduledTransactionDetail`; `register(mcp, client, settings) -> None`.
- **API note:** YNAB's scheduled-transaction update endpoint is a PUT (`ynab.PutScheduledTransactionWrapper` wraps the same `ynab.SaveScheduledTransaction` model used for create, which requires `account_id` and `date`). Unlike `bulk-manage-transactions`' patch-style update, `update` here needs the same required fields as `create` — there is no partial-update variant.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tools_scheduled_transactions.py`:

```python
"""Tests for ynab_mcp.tools.scheduled_transactions."""

from datetime import date
from types import SimpleNamespace

import ynab
from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

from ynab_mcp.tools.scheduled_transactions import (
    create_scheduled_transaction,
    delete_scheduled_transaction,
    update_scheduled_transaction,
)


def test_create_scheduled_transaction_calls_create(mocker: MockerFixture) -> None:
    """create_scheduled_transaction calls the SDK's create endpoint."""
    client = mocker.Mock()
    api = mocker.patch(
        "ynab_mcp.tools.scheduled_transactions.ynab.ScheduledTransactionsApi"
    )
    fake_scheduled = SimpleNamespace(id="st1")
    api.return_value.create_scheduled_transaction.return_value = SimpleNamespace(
        data=SimpleNamespace(scheduled_transaction=fake_scheduled)
    )

    result = create_scheduled_transaction(
        client, "budget-1", "acct-1", date(2024, 3, 1), -50000, "monthly"
    )

    assert result == fake_scheduled
    call = api.return_value.create_scheduled_transaction.call_args
    assert call.kwargs["plan_id"] == "budget-1"
    wrapper = call.kwargs["data"]
    assert wrapper.scheduled_transaction.account_id == "acct-1"
    assert wrapper.scheduled_transaction.amount == -50000
    assert wrapper.scheduled_transaction.frequency == "monthly"


def test_create_scheduled_transaction_raises_tool_error_on_api_exception(
    mocker: MockerFixture,
) -> None:
    """An ApiException from the SDK surfaces as a ToolError."""
    client = mocker.Mock()
    api = mocker.patch(
        "ynab_mcp.tools.scheduled_transactions.ynab.ScheduledTransactionsApi"
    )
    api.return_value.create_scheduled_transaction.side_effect = ynab.ApiException(
        status=400,
        reason="Bad Request",
        body='{"error": {"id": "400", "name": "bad_request", '
        '"detail": "Invalid account_id"}}',
    )

    with raises(ToolError, match="Invalid account_id"):
        create_scheduled_transaction(
            client, "budget-1", "bad-acct", date(2024, 3, 1), -50000, "monthly"
        )


def test_update_scheduled_transaction_calls_update(mocker: MockerFixture) -> None:
    """update_scheduled_transaction calls the SDK's update endpoint."""
    client = mocker.Mock()
    api = mocker.patch(
        "ynab_mcp.tools.scheduled_transactions.ynab.ScheduledTransactionsApi"
    )
    fake_scheduled = SimpleNamespace(id="st1")
    api.return_value.update_scheduled_transaction.return_value = SimpleNamespace(
        data=SimpleNamespace(scheduled_transaction=fake_scheduled)
    )

    result = update_scheduled_transaction(
        client, "budget-1", "st1", "acct-1", date(2024, 3, 1), -60000, "monthly"
    )

    assert result == fake_scheduled
    call = api.return_value.update_scheduled_transaction.call_args
    assert call.kwargs["plan_id"] == "budget-1"
    assert call.kwargs["scheduled_transaction_id"] == "st1"
    wrapper = call.kwargs["put_scheduled_transaction_wrapper"]
    assert wrapper.scheduled_transaction.amount == -60000


def test_update_scheduled_transaction_raises_tool_error_on_api_exception(
    mocker: MockerFixture,
) -> None:
    """An ApiException from the SDK surfaces as a ToolError."""
    client = mocker.Mock()
    api = mocker.patch(
        "ynab_mcp.tools.scheduled_transactions.ynab.ScheduledTransactionsApi"
    )
    api.return_value.update_scheduled_transaction.side_effect = ynab.ApiException(
        status=404,
        reason="Not Found",
        body='{"error": {"id": "404", "name": "not_found", '
        '"detail": "Scheduled transaction not found"}}',
    )

    with raises(ToolError, match="Scheduled transaction not found"):
        update_scheduled_transaction(
            client,
            "budget-1",
            "missing-st",
            "acct-1",
            date(2024, 3, 1),
            -60000,
            "monthly",
        )


def test_delete_scheduled_transaction_calls_delete(mocker: MockerFixture) -> None:
    """delete_scheduled_transaction calls the SDK's delete endpoint."""
    client = mocker.Mock()
    api = mocker.patch(
        "ynab_mcp.tools.scheduled_transactions.ynab.ScheduledTransactionsApi"
    )
    fake_scheduled = SimpleNamespace(id="st1", deleted=True)
    api.return_value.delete_scheduled_transaction.return_value = SimpleNamespace(
        data=SimpleNamespace(scheduled_transaction=fake_scheduled)
    )

    result = delete_scheduled_transaction(client, "budget-1", "st1")

    assert result == fake_scheduled
    api.return_value.delete_scheduled_transaction.assert_called_once_with(
        plan_id="budget-1", scheduled_transaction_id="st1"
    )


def test_delete_scheduled_transaction_raises_tool_error_on_api_exception(
    mocker: MockerFixture,
) -> None:
    """An ApiException from the SDK surfaces as a ToolError."""
    client = mocker.Mock()
    api = mocker.patch(
        "ynab_mcp.tools.scheduled_transactions.ynab.ScheduledTransactionsApi"
    )
    api.return_value.delete_scheduled_transaction.side_effect = ynab.ApiException(
        status=404,
        reason="Not Found",
        body='{"error": {"id": "404", "name": "not_found", '
        '"detail": "Scheduled transaction not found"}}',
    )

    with raises(ToolError, match="Scheduled transaction not found"):
        delete_scheduled_transaction(client, "budget-1", "missing-st")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_scheduled_transactions.py -v --tb=short`
Expected: FAIL — `ModuleNotFoundError: No module named 'ynab_mcp.tools.scheduled_transactions'`.

- [ ] **Step 3: Implement `scheduled_transactions.py`**

Create `src/ynab_mcp/tools/scheduled_transactions.py`:

```python
"""manage-scheduled-transaction tool: create/update/delete a recurring transaction."""

from datetime import date
from typing import Literal

import ynab
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from ynab_mcp.client import require_writable, resolve_budget_id
from ynab_mcp.config import Settings
from ynab_mcp.errors import translate_api_exception


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
        response = api.create_scheduled_transaction(
            plan_id=budget_id,
            data=ynab.PostScheduledTransactionWrapper(
                scheduled_transaction=ynab.SaveScheduledTransaction(
                    account_id=account_id,
                    date=date,
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
        response = api.update_scheduled_transaction(
            plan_id=budget_id,
            scheduled_transaction_id=scheduled_transaction_id,
            put_scheduled_transaction_wrapper=ynab.PutScheduledTransactionWrapper(
                scheduled_transaction=ynab.SaveScheduledTransaction(
                    account_id=account_id,
                    date=date,
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
        response = api.delete_scheduled_transaction(
            plan_id=budget_id, scheduled_transaction_id=scheduled_transaction_id
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
    def manage_scheduled_transaction_tool(
        operation: Literal["create", "update", "delete"],
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
    ) -> dict[str, object]:
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

        if operation == "delete":
            if scheduled_transaction_id is None:
                raise ToolError("delete requires scheduled_transaction_id.")
            scheduled_transaction = delete_scheduled_transaction(
                client, resolved_budget_id, scheduled_transaction_id
            )
            return scheduled_transaction.model_dump(mode="json")

        if account_id is None or date is None or amount is None or frequency is None:
            raise ToolError(
                f"{operation} requires account_id, date, amount, and frequency."
            )

        if operation == "create":
            scheduled_transaction = create_scheduled_transaction(
                client,
                resolved_budget_id,
                account_id,
                date,
                amount,
                frequency,
                payee_id=payee_id,
                payee_name=payee_name,
                category_id=category_id,
                memo=memo,
                flag_color=flag_color,
            )
        else:
            if scheduled_transaction_id is None:
                raise ToolError("update requires scheduled_transaction_id.")
            scheduled_transaction = update_scheduled_transaction(
                client,
                resolved_budget_id,
                scheduled_transaction_id,
                account_id,
                date,
                amount,
                frequency,
                payee_id=payee_id,
                payee_name=payee_name,
                category_id=category_id,
                memo=memo,
                flag_color=flag_color,
            )
        return scheduled_transaction.model_dump(mode="json")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_scheduled_transactions.py -v --tb=short`
Expected: PASS (6 tests).

- [ ] **Step 5: Lint and commit**

```bash
uv run black src/ynab_mcp/tools/scheduled_transactions.py tests/test_tools_scheduled_transactions.py
uv run ruff check src/ynab_mcp/tools/scheduled_transactions.py tests/test_tools_scheduled_transactions.py
uv run mypy
git add src/ynab_mcp/tools/scheduled_transactions.py tests/test_tools_scheduled_transactions.py
git commit -m "feat: add manage-scheduled-transaction tool"
git push
```

---

### Task 4: `manage-budgeted-amount` tool (assign + move with rollback)

**Files:**
- Create: `src/ynab_mcp/tools/budgeted_amount.py`
- Test: `tests/test_tools_budgeted_amount.py`

**Interfaces:**
- Consumes: `require_writable`, `resolve_budget_id` (Task 1); `translate_api_exception` (`errors.py`); `parse_month(value: str) -> date` from the existing `ynab_mcp.tools.months` module.
- Produces: `assign_budgeted_amount(client, budget_id, month, category_id, amount) -> ynab.Category`; `move_budgeted_amount(client, budget_id, month, from_category_id, to_category_id, amount) -> dict[str, ynab.Category]` (keys `"from_category"`, `"to_category"`); `register(mcp, client, settings) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tools_budgeted_amount.py`:

```python
"""Tests for ynab_mcp.tools.budgeted_amount."""

from types import SimpleNamespace

import ynab
from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

from ynab_mcp.tools.budgeted_amount import assign_budgeted_amount, move_budgeted_amount


def test_assign_budgeted_amount_calls_update_month_category(
    mocker: MockerFixture,
) -> None:
    """assign_budgeted_amount sets the category's budgeted amount for the month."""
    client = mocker.Mock()
    categories_api = mocker.patch("ynab_mcp.tools.budgeted_amount.ynab.CategoriesApi")
    fake_category = SimpleNamespace(id="cat-1", budgeted=50000)
    categories_api.return_value.update_month_category.return_value = SimpleNamespace(
        data=SimpleNamespace(category=fake_category)
    )

    result = assign_budgeted_amount(client, "budget-1", "current", "cat-1", 50000)

    assert result == fake_category
    call = categories_api.return_value.update_month_category.call_args
    assert call.kwargs["plan_id"] == "budget-1"
    assert call.kwargs["category_id"] == "cat-1"
    assert call.kwargs["data"].category.budgeted == 50000


def test_assign_budgeted_amount_raises_tool_error_on_api_exception(
    mocker: MockerFixture,
) -> None:
    """An ApiException from the SDK surfaces as a ToolError."""
    client = mocker.Mock()
    categories_api = mocker.patch("ynab_mcp.tools.budgeted_amount.ynab.CategoriesApi")
    categories_api.return_value.update_month_category.side_effect = (
        ynab.ApiException(
            status=404,
            reason="Not Found",
            body='{"error": {"id": "404", "name": "not_found", '
            '"detail": "Category not found"}}',
        )
    )

    with raises(ToolError, match="Category not found"):
        assign_budgeted_amount(client, "budget-1", "current", "missing-cat", 50000)


def test_move_budgeted_amount_decrements_source_and_increments_target(
    mocker: MockerFixture,
) -> None:
    """move_budgeted_amount reads both categories then shifts the amount."""
    client = mocker.Mock()
    categories_api = mocker.patch("ynab_mcp.tools.budgeted_amount.ynab.CategoriesApi")
    categories_api.return_value.get_month_category_by_id.side_effect = [
        SimpleNamespace(
            data=SimpleNamespace(category=SimpleNamespace(budgeted=100000))
        ),
        SimpleNamespace(
            data=SimpleNamespace(category=SimpleNamespace(budgeted=20000))
        ),
    ]
    updated_from = SimpleNamespace(id="from-cat", budgeted=80000)
    updated_to = SimpleNamespace(id="to-cat", budgeted=40000)
    categories_api.return_value.update_month_category.side_effect = [
        SimpleNamespace(data=SimpleNamespace(category=updated_from)),
        SimpleNamespace(data=SimpleNamespace(category=updated_to)),
    ]

    result = move_budgeted_amount(
        client, "budget-1", "current", "from-cat", "to-cat", 20000
    )

    assert result == {"from_category": updated_from, "to_category": updated_to}
    update_calls = categories_api.return_value.update_month_category.call_args_list
    assert update_calls[0].kwargs["category_id"] == "from-cat"
    assert update_calls[0].kwargs["data"].category.budgeted == 80000
    assert update_calls[1].kwargs["category_id"] == "to-cat"
    assert update_calls[1].kwargs["data"].category.budgeted == 40000


def test_move_budgeted_amount_rolls_back_source_on_target_failure(
    mocker: MockerFixture,
) -> None:
    """A failed target update restores the source's original amount and raises."""
    client = mocker.Mock()
    categories_api = mocker.patch("ynab_mcp.tools.budgeted_amount.ynab.CategoriesApi")
    categories_api.return_value.get_month_category_by_id.side_effect = [
        SimpleNamespace(
            data=SimpleNamespace(category=SimpleNamespace(budgeted=100000))
        ),
        SimpleNamespace(
            data=SimpleNamespace(category=SimpleNamespace(budgeted=20000))
        ),
    ]
    updated_from = SimpleNamespace(id="from-cat", budgeted=80000)
    rollback_response = SimpleNamespace(
        data=SimpleNamespace(
            category=SimpleNamespace(id="from-cat", budgeted=100000)
        )
    )
    categories_api.return_value.update_month_category.side_effect = [
        SimpleNamespace(data=SimpleNamespace(category=updated_from)),
        ynab.ApiException(
            status=404,
            reason="Not Found",
            body='{"error": {"id": "404", "name": "not_found", '
            '"detail": "Category not found"}}',
        ),
        rollback_response,
    ]

    with raises(ToolError, match="restored to its original budgeted amount"):
        move_budgeted_amount(
            client, "budget-1", "current", "from-cat", "missing-cat", 20000
        )

    update_calls = categories_api.return_value.update_month_category.call_args_list
    assert len(update_calls) == 3
    assert update_calls[2].kwargs["category_id"] == "from-cat"
    assert update_calls[2].kwargs["data"].category.budgeted == 100000


def test_move_budgeted_amount_reports_failed_rollback(mocker: MockerFixture) -> None:
    """If the rollback also fails, the error names the inconsistent state."""
    client = mocker.Mock()
    categories_api = mocker.patch("ynab_mcp.tools.budgeted_amount.ynab.CategoriesApi")
    categories_api.return_value.get_month_category_by_id.side_effect = [
        SimpleNamespace(
            data=SimpleNamespace(category=SimpleNamespace(budgeted=100000))
        ),
        SimpleNamespace(
            data=SimpleNamespace(category=SimpleNamespace(budgeted=20000))
        ),
    ]
    updated_from = SimpleNamespace(id="from-cat", budgeted=80000)
    categories_api.return_value.update_month_category.side_effect = [
        SimpleNamespace(data=SimpleNamespace(category=updated_from)),
        ynab.ApiException(
            status=404,
            reason="Not Found",
            body='{"error": {"id": "404", "name": "not_found", '
            '"detail": "Category not found"}}',
        ),
        ynab.ApiException(
            status=500,
            reason="Server Error",
            body='{"error": {"id": "500", "name": "internal", '
            '"detail": "Service unavailable"}}',
        ),
    ]

    with raises(ToolError, match="Rollback of the source category also failed"):
        move_budgeted_amount(
            client, "budget-1", "current", "from-cat", "missing-cat", 20000
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_budgeted_amount.py -v --tb=short`
Expected: FAIL — `ModuleNotFoundError: No module named 'ynab_mcp.tools.budgeted_amount'`.

- [ ] **Step 3: Implement `budgeted_amount.py`**

Create `src/ynab_mcp/tools/budgeted_amount.py`:

```python
"""manage-budgeted-amount tool: assign or move budgeted amounts between categories."""

from typing import Literal

import ynab
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from ynab_mcp.client import require_writable, resolve_budget_id
from ynab_mcp.config import Settings
from ynab_mcp.errors import translate_api_exception
from ynab_mcp.tools.months import parse_month


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
        response = api.update_month_category(
            plan_id=budget_id,
            month=resolved_month,
            category_id=category_id,
            data=ynab.PatchMonthCategoryWrapper(
                category=ynab.SaveMonthCategory(budgeted=amount)
            ),
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
        If ``month`` is invalid, if reading either category fails, or if
        the move itself fails. When the target update fails after the
        source was decremented, the error states whether the rollback
        succeeded or, if it also failed, exactly which category/month/
        amount is left inconsistent.
    """
    resolved_month = parse_month(month)
    api = ynab.CategoriesApi(client)
    try:
        from_current = api.get_month_category_by_id(
            plan_id=budget_id, month=resolved_month, category_id=from_category_id
        ).data.category.budgeted
        to_current = api.get_month_category_by_id(
            plan_id=budget_id, month=resolved_month, category_id=to_category_id
        ).data.category.budgeted
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc

    try:
        from_category = api.update_month_category(
            plan_id=budget_id,
            month=resolved_month,
            category_id=from_category_id,
            data=ynab.PatchMonthCategoryWrapper(
                category=ynab.SaveMonthCategory(budgeted=from_current - amount)
            ),
        ).data.category
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc

    try:
        to_category = api.update_month_category(
            plan_id=budget_id,
            month=resolved_month,
            category_id=to_category_id,
            data=ynab.PatchMonthCategoryWrapper(
                category=ynab.SaveMonthCategory(budgeted=to_current + amount)
            ),
        ).data.category
    except ynab.ApiException as exc:
        target_detail = str(translate_api_exception(exc))
        try:
            api.update_month_category(
                plan_id=budget_id,
                month=resolved_month,
                category_id=from_category_id,
                data=ynab.PatchMonthCategoryWrapper(
                    category=ynab.SaveMonthCategory(budgeted=from_current)
                ),
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
    def manage_budgeted_amount_tool(
        operation: Literal["assign", "move"],
        month: str,
        category_id: str | None = None,
        amount: int | None = None,
        from_category_id: str | None = None,
        to_category_id: str | None = None,
        budget_id: str | None = None,
    ) -> dict[str, object]:
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
        if operation == "assign":
            if category_id is None or amount is None:
                raise ToolError("assign requires category_id and amount.")
            category = assign_budgeted_amount(
                client, resolved_budget_id, month, category_id, amount
            )
            return category.model_dump(mode="json")

        if from_category_id is None or to_category_id is None or amount is None:
            raise ToolError(
                "move requires from_category_id, to_category_id, and amount."
            )
        result = move_budgeted_amount(
            client,
            resolved_budget_id,
            month,
            from_category_id,
            to_category_id,
            amount,
        )
        return {
            "from_category": result["from_category"].model_dump(mode="json"),
            "to_category": result["to_category"].model_dump(mode="json"),
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_budgeted_amount.py -v --tb=short`
Expected: PASS (5 tests).

- [ ] **Step 5: Lint and commit**

```bash
uv run black src/ynab_mcp/tools/budgeted_amount.py tests/test_tools_budgeted_amount.py
uv run ruff check src/ynab_mcp/tools/budgeted_amount.py tests/test_tools_budgeted_amount.py
uv run mypy
git add src/ynab_mcp/tools/budgeted_amount.py tests/test_tools_budgeted_amount.py
git commit -m "feat: add manage-budgeted-amount tool (assign + move with rollback)"
git push
```

---

### Task 5: `bulk-manage-transactions` tool

**Files:**
- Create: `src/ynab_mcp/tools/transactions_write.py`
- Test: `tests/test_tools_transactions_write.py`

**Interfaces:**
- Consumes: `require_writable`, `resolve_budget_id` (Task 1); `translate_api_exception` (`errors.py`).
- Produces: `TransactionOperationResult` (a `TypedDict` with keys `action: str`, `id: str | None`, `status: Literal["ok", "error"]`, `detail: str | None`); `bulk_manage_transactions(client, budget_id, operations: list[dict[str, object]]) -> list[TransactionOperationResult]`; `register(mcp, client, settings) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tools_transactions_write.py`:

```python
"""Tests for ynab_mcp.tools.transactions_write."""

from types import SimpleNamespace

import ynab
from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

from ynab_mcp.tools.transactions_write import bulk_manage_transactions


def test_bulk_manage_transactions_requires_at_least_one_operation() -> None:
    """An empty operations list is a caller error, not a YNAB call."""
    client = SimpleNamespace()

    with raises(ToolError, match="at least one operation"):
        bulk_manage_transactions(client, "budget-1", [])


def test_bulk_manage_transactions_rejects_unknown_action() -> None:
    """An operation with an invalid action raises before any API call."""
    client = SimpleNamespace()

    with raises(ToolError, match="action must be one of"):
        bulk_manage_transactions(client, "budget-1", [{"action": "archive"}])


def test_bulk_manage_transactions_rejects_update_without_id() -> None:
    """An update operation missing 'id' raises before any API call."""
    client = SimpleNamespace()

    with raises(ToolError, match="update requires 'id'"):
        bulk_manage_transactions(client, "budget-1", [{"action": "update"}])


def test_bulk_manage_transactions_rejects_create_without_account_id() -> None:
    """A create operation missing 'account_id' raises before any API call."""
    client = SimpleNamespace()

    with raises(ToolError, match="create requires 'account_id'"):
        bulk_manage_transactions(client, "budget-1", [{"action": "create"}])


def test_bulk_manage_transactions_handles_mixed_batch(mocker: MockerFixture) -> None:
    """A batch with one create, one update, and one delete runs all three."""
    client = mocker.Mock()
    transactions_api = mocker.patch(
        "ynab_mcp.tools.transactions_write.ynab.TransactionsApi"
    )
    transactions_api.return_value.create_transaction.return_value = SimpleNamespace(
        data=SimpleNamespace(transactions=[SimpleNamespace(id="new-1")])
    )
    transactions_api.return_value.update_transactions.return_value = SimpleNamespace(
        data=SimpleNamespace(transactions=[SimpleNamespace(id="txn-1")])
    )
    transactions_api.return_value.delete_transaction.return_value = SimpleNamespace(
        data=SimpleNamespace(transaction=SimpleNamespace(id="txn-2"))
    )

    operations: list[dict[str, object]] = [
        {"action": "create", "account_id": "acct-1", "amount": -5000},
        {"action": "update", "id": "txn-1", "category_id": "cat-1"},
        {"action": "delete", "id": "txn-2"},
    ]

    result = bulk_manage_transactions(client, "budget-1", operations)

    assert result == [
        {"action": "create", "id": "new-1", "status": "ok", "detail": None},
        {"action": "update", "id": "txn-1", "status": "ok", "detail": None},
        {"action": "delete", "id": "txn-2", "status": "ok", "detail": None},
    ]

    create_call = transactions_api.return_value.create_transaction.call_args
    assert create_call.kwargs["plan_id"] == "budget-1"
    created_wrapper = create_call.kwargs["data"]
    assert created_wrapper.transactions[0].account_id == "acct-1"
    assert created_wrapper.transactions[0].amount == -5000

    update_call = transactions_api.return_value.update_transactions.call_args
    updated_wrapper = update_call.kwargs["data"]
    assert updated_wrapper.transactions[0].id == "txn-1"
    assert updated_wrapper.transactions[0].category_id == "cat-1"

    transactions_api.return_value.delete_transaction.assert_called_once_with(
        plan_id="budget-1", transaction_id="txn-2"
    )


def test_bulk_manage_transactions_reports_per_item_failure(
    mocker: MockerFixture,
) -> None:
    """A failure in one group doesn't block the others' results."""
    client = mocker.Mock()
    transactions_api = mocker.patch(
        "ynab_mcp.tools.transactions_write.ynab.TransactionsApi"
    )
    transactions_api.return_value.update_transactions.return_value = SimpleNamespace(
        data=SimpleNamespace(transactions=[SimpleNamespace(id="txn-1")])
    )
    transactions_api.return_value.delete_transaction.side_effect = ynab.ApiException(
        status=404,
        reason="Not Found",
        body='{"error": {"id": "404", "name": "not_found", '
        '"detail": "Transaction not found"}}',
    )

    operations: list[dict[str, object]] = [
        {"action": "update", "id": "txn-1", "category_id": "cat-1"},
        {"action": "delete", "id": "missing-txn"},
    ]

    result = bulk_manage_transactions(client, "budget-1", operations)

    assert result[0] == {
        "action": "update",
        "id": "txn-1",
        "status": "ok",
        "detail": None,
    }
    assert result[1]["status"] == "error"
    assert result[1]["detail"] == "Transaction not found"


def test_bulk_manage_transactions_marks_whole_create_group_error_on_batch_failure(
    mocker: MockerFixture,
) -> None:
    """A failed grouped create call marks every create item as an error."""
    client = mocker.Mock()
    transactions_api = mocker.patch(
        "ynab_mcp.tools.transactions_write.ynab.TransactionsApi"
    )
    transactions_api.return_value.create_transaction.side_effect = ynab.ApiException(
        status=400,
        reason="Bad Request",
        body='{"error": {"id": "400", "name": "bad_request", '
        '"detail": "Invalid account_id"}}',
    )

    operations: list[dict[str, object]] = [
        {"action": "create", "account_id": "bad-acct", "amount": -1000},
        {"action": "create", "account_id": "bad-acct", "amount": -2000},
    ]

    result = bulk_manage_transactions(client, "budget-1", operations)

    assert all(item["status"] == "error" for item in result)
    assert all(item["detail"] == "Invalid account_id" for item in result)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_transactions_write.py -v --tb=short`
Expected: FAIL — `ModuleNotFoundError: No module named 'ynab_mcp.tools.transactions_write'`.

- [ ] **Step 3: Implement `transactions_write.py`**

Create `src/ynab_mcp/tools/transactions_write.py`:

```python
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

    create_indices = [
        i for i, op in enumerate(operations) if op["action"] == "create"
    ]
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
        except ynab.ApiException as exc:
            detail = str(translate_api_exception(exc))
            for i in create_indices:
                results[i] = {
                    "action": "create",
                    "id": None,
                    "status": "error",
                    "detail": detail,
                }

    update_indices = [
        i for i, op in enumerate(operations) if op["action"] == "update"
    ]
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
        except ynab.ApiException as exc:
            detail = str(translate_api_exception(exc))
            for i in update_indices:
                results[i] = {
                    "action": "update",
                    "id": str(operations[i]["id"]),
                    "status": "error",
                    "detail": detail,
                }

    delete_indices = [
        i for i, op in enumerate(operations) if op["action"] == "delete"
    ]
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_transactions_write.py -v --tb=short`
Expected: PASS (7 tests).

- [ ] **Step 5: Lint and commit**

```bash
uv run black src/ynab_mcp/tools/transactions_write.py tests/test_tools_transactions_write.py
uv run ruff check src/ynab_mcp/tools/transactions_write.py tests/test_tools_transactions_write.py
uv run mypy
git add src/ynab_mcp/tools/transactions_write.py tests/test_tools_transactions_write.py
git commit -m "feat: add bulk-manage-transactions tool"
git push
```

---

### Task 6: Wire all four tools into `server.py`

**Files:**
- Modify: `src/ynab_mcp/server.py`
- Modify: `tests/test_server.py`
- Modify: `tests/test_e2e_server.py`

**Interfaces:**
- Consumes: `transactions_write.register`, `budgeted_amount.register`, `payees_write.register`, `scheduled_transactions.register` (Tasks 2-5).

- [ ] **Step 1: Write the failing tests**

In `tests/test_server.py`, update the import line to add `ToolError`:

```python
"""Tests for ynab_mcp.server."""

import asyncio

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from ynab_mcp.server import build_server
```

Replace the body of `test_build_server_registers_all_other_tools` and add two new tests after it:

```python
def test_build_server_registers_all_other_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every non-list-budgets tool is always registered."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("YNAB_PAT", "test-token")
    monkeypatch.setenv("YNAB_DEFAULT_BUDGET_ID", "budget-123")

    mcp = build_server()

    tool_names = _list_tool_names(mcp)
    assert tool_names == {
        "list-accounts",
        "list-categories",
        "list-transactions",
        "get-month-info",
        "list-payees",
        "lookup-entity-by-id",
        "bulk-manage-transactions",
        "manage-budgeted-amount",
        "manage-payees",
        "manage-scheduled-transaction",
    }


def test_write_tools_registered_regardless_of_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Write tools are discoverable even when YNAB_READ_ONLY=true."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("YNAB_PAT", "test-token")
    monkeypatch.setenv("YNAB_DEFAULT_BUDGET_ID", "budget-123")
    monkeypatch.setenv("YNAB_READ_ONLY", "true")

    mcp = build_server()

    tool_names = _list_tool_names(mcp)
    assert {
        "bulk-manage-transactions",
        "manage-budgeted-amount",
        "manage-payees",
        "manage-scheduled-transaction",
    }.issubset(tool_names)


def test_write_tools_blocked_when_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every write tool raises a read-only ToolError before touching the API."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("YNAB_PAT", "test-token")
    monkeypatch.setenv("YNAB_DEFAULT_BUDGET_ID", "budget-123")
    monkeypatch.setenv("YNAB_READ_ONLY", "true")

    mcp = build_server()

    calls: dict[str, dict[str, object]] = {
        "manage-payees": {"operation": "rename"},
        "manage-scheduled-transaction": {"operation": "delete"},
        "manage-budgeted-amount": {"operation": "assign", "month": "current"},
        "bulk-manage-transactions": {"operations": []},
    }

    async def _call_all() -> None:
        async with Client(mcp) as client:
            for name, args in calls.items():
                with pytest.raises(ToolError, match="YNAB_READ_ONLY"):
                    await client.call_tool(name, args)

    asyncio.run(_call_all())
```

In `tests/test_e2e_server.py`, update the expected tool-name set in
`test_uv_run_ynab_mcp_stdio_server_lists_expected_tools`:

```python
    assert tool_names == {
        "list-budgets",
        "list-accounts",
        "list-categories",
        "list-transactions",
        "get-month-info",
        "list-payees",
        "lookup-entity-by-id",
        "bulk-manage-transactions",
        "manage-budgeted-amount",
        "manage-payees",
        "manage-scheduled-transaction",
    }
```

Also update that test's docstring's `"real 7 read-only tools"` wording to `"real 11 tools (7 read-only + 4 write)"` since it's no longer accurate.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_server.py -v --tb=short`
Expected: FAIL — `test_build_server_registers_all_other_tools` asserts a set missing the 4 new names (they aren't registered yet); `test_write_tools_registered_regardless_of_read_only` and `test_write_tools_blocked_when_read_only` fail with `fastmcp.exceptions.ToolError: Unknown tool` (or equivalent "not found") since the tools don't exist yet.

- [ ] **Step 3: Wire the tools into `build_server()`**

In `src/ynab_mcp/server.py`, update the import block and `build_server()` body:

```python
"""FastMCP stdio server exposing read-only and write YNAB tools."""

from fastmcp import FastMCP

from ynab_mcp.client import build_api_client
from ynab_mcp.config import Settings
from ynab_mcp.tools import (
    accounts,
    budgeted_amount,
    budgets,
    categories,
    lookup,
    months,
    payees,
    payees_write,
    scheduled_transactions,
    transactions,
    transactions_write,
)


def build_server() -> FastMCP:
    """Build and wire the YNAB MCP server.

    Reads configuration from the environment, constructs a shared YNAB API
    client, and registers every tool. ``list-budgets`` is registered only
    when no default budget is configured. Write tools are always
    registered -- ``YNAB_READ_ONLY`` is enforced per-call by each write
    tool, not by hiding the tools from discovery.

    Returns
    -------
    fastmcp.FastMCP
        A fully configured server, ready to run over stdio.

    Raises
    ------
    RuntimeError
        If ``YNAB_PAT`` is not configured.
    """
    settings = Settings.from_env()
    client = build_api_client(settings)
    mcp = FastMCP("ynab-mcp")

    if settings.ynab_default_budget_id is None:
        budgets.register(mcp, client)
    accounts.register(mcp, client, settings)
    categories.register(mcp, client, settings)
    transactions.register(mcp, client, settings)
    months.register(mcp, client, settings)
    payees.register(mcp, client, settings)
    lookup.register(mcp, client, settings)
    transactions_write.register(mcp, client, settings)
    budgeted_amount.register(mcp, client, settings)
    payees_write.register(mcp, client, settings)
    scheduled_transactions.register(mcp, client, settings)

    return mcp


def main() -> None:
    """Build and run the YNAB MCP server over stdio."""
    build_server().run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_server.py -v --tb=short`
Expected: PASS (7 tests).

Then run the full non-e2e suite:

Run: `uv run pytest -v --tb=short`
Expected: PASS (all tests, including every task's tests above).

Then run e2e:

Run: `uv run pytest -m e2e -v --tb=short`
Expected: PASS (1 test, real stdio subprocess lists all 11 tools).

- [ ] **Step 5: Lint and commit**

```bash
uv run black src/ynab_mcp/server.py tests/test_server.py tests/test_e2e_server.py
uv run ruff check src/ynab_mcp/server.py tests/test_server.py tests/test_e2e_server.py
uv run mypy
git add src/ynab_mcp/server.py tests/test_server.py tests/test_e2e_server.py
git commit -m "feat: register all four write tools on the server"
git push
```

---

### Task 7: Full quality gate

**Files:** none (verification only).

- [ ] **Step 1: Run the full lint + test gate**

```bash
make lint
make tests
make e2e
```

Expected: all three succeed with no errors.

- [ ] **Step 2: Run the coverage gate**

```bash
make coverage
```

Expected: succeeds, coverage >= 80%.

- [ ] **Step 3: Run the security scan**

```bash
make security
```

Expected: no new high-severity findings introduced by this feature (bandit scans `src/` for common issues; this feature adds no subprocess/eval/pickle usage, so no findings are expected).

---

## Self-Review Notes

- **Spec coverage:** all four tools from the spec have a task (Tasks 2-5); the shared guard has its own task (Task 1); server wiring has its own task (Task 6); the quality gate closes the loop (Task 7). The scheduled-transaction "update requires full state, not a subset" correction was applied to both this plan and the spec doc.
- **Placeholder scan:** none — every step has complete, runnable code.
- **Type consistency:** `require_writable(settings: Settings) -> None` (Task 1) is called identically in Tasks 2-5's `register()` closures. `TransactionOperationResult` (Task 5) is used consistently as the return type of both `bulk_manage_transactions` and the registered tool closure. `move_budgeted_amount`'s return type `dict[str, ynab.Category]` with keys `"from_category"`/`"to_category"` matches its Task 4 test assertions and its `register()` closure's post-processing.
