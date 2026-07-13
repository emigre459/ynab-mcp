# Core YNAB MCP Server Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a FastMCP v3 stdio MCP server exposing read-only YNAB data (budgets, accounts, categories, transactions, payees, month info, generic entity lookup) via the official `ynab` PyPI client, closing issue #11.

**Architecture:** A layered `src/ynab_mcp/` package — `config.py` (env-driven `Settings`), `client.py` (shared `ynab.ApiClient` + budget-id resolution), `errors.py` (YNAB `ApiException` → `fastmcp.exceptions.ToolError` translation), `tools/` (one module per tool group, each exposing a plain testable function plus a thin `@mcp.tool`-registering function), and `server.py` (wires it all together and runs the stdio transport). Full design rationale: `docs/superpowers/specs/2026-07-12-core-ynab-mcp-server-design.md`.

**Tech Stack:** Python 3.13, `fastmcp` v3, `ynab` v4.2.0 (official YNAB client — internally uses `PlansApi`/`plan_id`, but our public surface uses "budget" terminology throughout, translated at the `client.py` boundary), `uv`, `pytest` + `pytest-mock`.

## Global Constraints

- Public surface (env vars, tool names, parameters, docstrings) uses "budget" terminology (`budget_id`, `YNAB_DEFAULT_BUDGET_ID`, `list-budgets`) even though the `ynab` SDK internally uses `plan_id`/`PlansApi`. Translation happens only in `client.py`.
- `YNAB_PAT` is required; missing/empty raises `RuntimeError` at server startup (fail-hard-not-warn, per `.agents/rules/shared/fail-hard-not-warn.md`).
- `YNAB_READ_ONLY` is parsed (default `True`) but **not enforced** in this card — no write tools exist yet (epic #10 child 2).
- Every tool except `list-budgets` takes an optional `budget_id: str | None`, falling back to `YNAB_DEFAULT_BUDGET_ID` via `resolve_budget_id`, raising `ToolError` if neither is present.
- `list-budgets` is registered only when `YNAB_DEFAULT_BUDGET_ID` is unset.
- YNAB API errors always surface as `fastmcp.exceptions.ToolError` carrying YNAB's real error detail — never masked (per `.agents/rules/shared/fail-hard-not-warn.md` and the approved spec).
- NumPy-style docstrings on every function/class in `src/` (one-line summary + `Parameters`/`Returns`/`Raises` as applicable), per `.agents/rules/python/python-best-practices.md`. Test files are exempt from ruff's docstring checks but still get a one-line docstring per house style.
- `X | None` (PEP 604), not `Optional[X]`.
- `.env` is loaded via `load_dotenv()` before reading env vars, per `.agents/rules/python/load-dotenv-first.md`.
- All commands via `uv run` / `uv add`, never bare `pip`/`python`, per `.agents/rules/python/uv-python.md`.
- `make lint` (black --check + ruff + mypy) and `make coverage` (pytest, 80% gate) must pass; `mypy` has `disallow_untyped_defs = True` covering both `src/` and `tests/` — every function (including tests) needs full type annotations.
- Push after every commit (`.agents/rules/shared/push-every-commit.md`).

---

### Task 1: Project scaffolding — dependencies + package rename

**Files:**
- Modify: `pyproject.toml`
- Delete: `src/example_app/__init__.py`, `src/example_app/greeting.py`, `tests/test_greeting.py`
- Create: `src/ynab_mcp/__init__.py`

**Interfaces:**
- Produces: the `ynab_mcp` package (empty `__init__.py` for now), `fastmcp`/`ynab` runtime deps, `pytest-mock` dev dep — every later task imports from `ynab_mcp.*` and uses the `mocker` fixture.

- [ ] **Step 1: Add runtime and dev dependencies**

Run:
```bash
uv add fastmcp ynab
uv add pytest-mock --dev
```

Expected: `pyproject.toml`'s `dependencies` gains `fastmcp` and `ynab`; `[dependency-groups] dev` gains `pytest-mock`. `uv.lock` is updated.

- [ ] **Step 2: Remove the template placeholder package**

```bash
git rm -r src/example_app tests/test_greeting.py
mkdir -p src/ynab_mcp
```

Create `src/ynab_mcp/__init__.py`:

```python
"""FastMCP stdio server exposing read-only YNAB data."""
```

- [ ] **Step 3: Point pyproject.toml at the real package and drop stale template comments**

In `pyproject.toml`, replace:

```toml
[project]
# Placeholder name/description — replaced by scripts/init_template.py at `make init`.
# Kept as a PEP 508-valid identifier so `uv sync` succeeds pre-init; the unique
# token below (and `MCP server for YNAB` literal) are the substitution targets.
name = "ynab-mcp"
```

with:

```toml
[project]
name = "ynab-mcp"
```

And replace:

```toml
[tool.uv.build-backend]
# Sample package lives at `src/example_app/`; init swaps both the project name
# and this module-name to the user's chosen package at `make init`.
module-name = "example_app"
```

with:

```toml
[tool.uv.build-backend]
module-name = "ynab_mcp"
```

(Leave the `uv add`-managed `dependencies` and `dependency-groups` blocks from Step 1 as-is — do not hand-edit version pins.)

- [ ] **Step 4: Verify the environment installs cleanly**

Run: `uv sync --dev`
Expected: exits 0, `.venv` now has `fastmcp`, `ynab`, `pytest-mock` installed, no reference to `example_app` remains.

Run: `uv run python -c "import ynab_mcp; import fastmcp; import ynab"`
Expected: exits 0 with no output (no import errors).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock src/ynab_mcp/__init__.py
git add -u src/example_app tests/test_greeting.py
git commit -m "chore: replace template placeholder with ynab_mcp package scaffold"
git push
```

---

### Task 2: `config.py` — environment-driven Settings

**Files:**
- Create: `src/ynab_mcp/config.py`
- Create: `tests/test_config.py`
- Create: `.env.example`

**Interfaces:**
- Consumes: nothing from earlier tasks (only stdlib + `python-dotenv`, already a dependency).
- Produces: `Settings` frozen dataclass with fields `ynab_pat: str`, `ynab_default_budget_id: str | None`, `ynab_read_only: bool`, and classmethod `Settings.from_env() -> Settings`. Every later task that needs config imports `from ynab_mcp.config import Settings`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_config.py`:

```python
"""Tests for ynab_mcp.config."""

import pytest

from ynab_mcp.config import Settings


def test_from_env_reads_required_and_optional_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """All three env vars are read into Settings when present."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("YNAB_PAT", "test-token")
    monkeypatch.setenv("YNAB_DEFAULT_BUDGET_ID", "budget-123")
    monkeypatch.setenv("YNAB_READ_ONLY", "false")

    settings = Settings.from_env()

    assert settings.ynab_pat == "test-token"
    assert settings.ynab_default_budget_id == "budget-123"
    assert settings.ynab_read_only is False


def test_from_env_defaults_when_optional_vars_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing optional vars fall back to None / True."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("YNAB_PAT", "test-token")
    monkeypatch.delenv("YNAB_DEFAULT_BUDGET_ID", raising=False)
    monkeypatch.delenv("YNAB_READ_ONLY", raising=False)

    settings = Settings.from_env()

    assert settings.ynab_default_budget_id is None
    assert settings.ynab_read_only is True


@pytest.mark.parametrize("raw_value", ["false", "0", "no", "FALSE", "No"])
def test_from_env_parses_read_only_false_variants(
    monkeypatch: pytest.MonkeyPatch, raw_value: str
) -> None:
    """Common falsy spellings of YNAB_READ_ONLY parse to False."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("YNAB_PAT", "test-token")
    monkeypatch.setenv("YNAB_READ_ONLY", raw_value)

    settings = Settings.from_env()

    assert settings.ynab_read_only is False


def test_from_env_raises_when_pat_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing YNAB_PAT fails hard with a remediation hint."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("YNAB_PAT", raising=False)

    with pytest.raises(RuntimeError, match="YNAB_PAT"):
        Settings.from_env()


def test_from_env_raises_when_pat_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """A blank YNAB_PAT is treated the same as missing."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("YNAB_PAT", "   ")

    with pytest.raises(RuntimeError, match="YNAB_PAT"):
        Settings.from_env()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ynab_mcp.config'`

- [ ] **Step 3: Write the implementation**

Create `src/ynab_mcp/config.py`:

```python
"""Server configuration read from the environment."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

_FALSY_VALUES = {"false", "0", "no"}


@dataclass(frozen=True)
class Settings:
    """Runtime configuration for the YNAB MCP server.

    Parameters
    ----------
    ynab_pat : str
        The YNAB personal access token used to authenticate API calls.
    ynab_default_budget_id : str | None
        A budget id every tool falls back to when the caller omits one.
    ynab_read_only : bool
        Whether write/mutation tools are permitted. Currently read but
        unenforced -- no write tools exist yet.
    """

    ynab_pat: str
    ynab_default_budget_id: str | None
    ynab_read_only: bool

    @classmethod
    def from_env(cls) -> "Settings":
        """Build ``Settings`` from the process environment.

        Loads `.env` first, then reads ``YNAB_PAT``,
        ``YNAB_DEFAULT_BUDGET_ID``, and ``YNAB_READ_ONLY``.

        Returns
        -------
        Settings
            The parsed server configuration.

        Raises
        ------
        RuntimeError
            If ``YNAB_PAT`` is missing or empty.
        """
        load_dotenv()

        ynab_pat = os.environ.get("YNAB_PAT", "").strip()
        if not ynab_pat:
            raise RuntimeError(
                "YNAB_PAT is not set. Copy .env.example to .env and set "
                "YNAB_PAT to a YNAB personal access token "
                "(https://api.ynab.com/#personal-access-tokens)."
            )

        default_budget_id = (
            os.environ.get("YNAB_DEFAULT_BUDGET_ID", "").strip() or None
        )

        read_only_raw = os.environ.get("YNAB_READ_ONLY", "true").strip().lower()
        ynab_read_only = read_only_raw not in _FALSY_VALUES

        return cls(
            ynab_pat=ynab_pat,
            ynab_default_budget_id=default_budget_id,
            ynab_read_only=ynab_read_only,
        )
```

Create `.env.example` at the repo root:

```
# YNAB personal access token. Create one at
# https://api.ynab.com/#personal-access-tokens
YNAB_PAT=

# Optional: a budget id every tool falls back to when the caller omits one.
# When set, the list-budgets tool is hidden (there's only one budget context).
YNAB_DEFAULT_BUDGET_ID=

# Optional: defaults to true. Currently read but not enforced -- no write
# tools exist yet.
YNAB_READ_ONLY=true
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/config.py tests/test_config.py .env.example
git commit -m "feat: add env-driven Settings for the YNAB MCP server"
git push
```

---

### Task 3: `errors.py` — YNAB `ApiException` → `ToolError` translation

**Files:**
- Create: `src/ynab_mcp/errors.py`
- Create: `tests/test_errors.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `translate_api_exception(exc: ynab.ApiException) -> fastmcp.exceptions.ToolError`, imported by `client.py` (Task 4) and every `tools/*.py` module (Tasks 5-11).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_errors.py`:

```python
"""Tests for ynab_mcp.errors."""

import ynab
from fastmcp.exceptions import ToolError

from ynab_mcp.errors import translate_api_exception


def test_translate_api_exception_extracts_detail_from_body() -> None:
    """The YNAB error detail is pulled out of the JSON response body."""
    exc = ynab.ApiException(
        status=404,
        reason="Not Found",
        body='{"error": {"id": "404", "name": "not_found", '
        '"detail": "Budget not found"}}',
    )

    result = translate_api_exception(exc)

    assert isinstance(result, ToolError)
    assert "Budget not found" in str(result)


def test_translate_api_exception_falls_back_when_body_missing() -> None:
    """A missing body still produces a useful, non-empty message."""
    exc = ynab.ApiException(status=500, reason="Internal Server Error", body=None)

    result = translate_api_exception(exc)

    assert "500" in str(result)
    assert "Internal Server Error" in str(result)


def test_translate_api_exception_falls_back_when_body_malformed() -> None:
    """A body that isn't the expected error JSON shape doesn't crash."""
    exc = ynab.ApiException(status=502, reason="Bad Gateway", body="not json")

    result = translate_api_exception(exc)

    assert "502" in str(result)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_errors.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ynab_mcp.errors'`

- [ ] **Step 3: Write the implementation**

Create `src/ynab_mcp/errors.py`:

```python
"""Translate YNAB SDK exceptions into FastMCP ToolError instances."""

import json
import logging

import ynab
from fastmcp.exceptions import ToolError

logger = logging.getLogger(__name__)


def translate_api_exception(exc: ynab.ApiException) -> ToolError:
    """Convert a YNAB ``ApiException`` into a FastMCP ``ToolError``.

    Parameters
    ----------
    exc : ynab.ApiException
        The exception raised by a ``ynab`` SDK API call.

    Returns
    -------
    fastmcp.exceptions.ToolError
        A ``ToolError`` carrying the YNAB API's error detail message, ready
        to be raised so the MCP client sees the real failure reason.
    """
    detail = _extract_detail(exc)
    logger.error("YNAB API request failed (status=%s): %s", exc.status, detail)
    return ToolError(detail)


def _extract_detail(exc: ynab.ApiException) -> str:
    """Pull the YNAB error ``detail`` field out of an API exception body.

    Parameters
    ----------
    exc : ynab.ApiException
        The exception raised by a ``ynab`` SDK API call.

    Returns
    -------
    str
        The YNAB API's error detail message, or a generic fallback if the
        response body is missing or not in the expected shape.
    """
    if not exc.body:
        return f"YNAB API request failed with status {exc.status}: {exc.reason}"
    try:
        payload = json.loads(exc.body)
        return str(payload["error"]["detail"])
    except (json.JSONDecodeError, KeyError, TypeError):
        return f"YNAB API request failed with status {exc.status}: {exc.body}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_errors.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/errors.py tests/test_errors.py
git commit -m "feat: translate YNAB ApiException into ToolError"
git push
```

---

### Task 4: `client.py` — API client factory + budget-id resolution

**Files:**
- Create: `src/ynab_mcp/client.py`
- Create: `tests/test_client.py`

**Interfaces:**
- Consumes: `Settings` (Task 2).
- Produces: `build_api_client(settings: Settings) -> ynab.ApiClient`, `resolve_budget_id(budget_id: str | None, settings: Settings) -> str`. Both imported by `server.py` (Task 12) and every `tools/*.py` module that needs a default-budget fallback (Tasks 6-11; `budgets.py` in Task 5 doesn't need `resolve_budget_id`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_client.py`:

```python
"""Tests for ynab_mcp.client."""

import pytest
from fastmcp.exceptions import ToolError

from ynab_mcp.client import build_api_client, resolve_budget_id
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
    settings = Settings(
        ynab_pat="x", ynab_default_budget_id=None, ynab_read_only=True
    )

    with pytest.raises(ToolError, match="budget_id"):
        resolve_budget_id(None, settings)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ynab_mcp.client'`

- [ ] **Step 3: Write the implementation**

Create `src/ynab_mcp/client.py`:

```python
"""YNAB API client construction and budget-id resolution."""

import ynab
from fastmcp.exceptions import ToolError

from ynab_mcp.config import Settings


def build_api_client(settings: Settings) -> ynab.ApiClient:
    """Construct a YNAB ``ApiClient`` from server settings.

    Parameters
    ----------
    settings : Settings
        The server's parsed configuration; only ``ynab_pat`` is used.

    Returns
    -------
    ynab.ApiClient
        A configured API client, reused for the server's process lifetime.
    """
    configuration = ynab.Configuration(access_token=settings.ynab_pat)
    return ynab.ApiClient(configuration)


def resolve_budget_id(budget_id: str | None, settings: Settings) -> str:
    """Resolve an explicit or default YNAB budget id.

    Parameters
    ----------
    budget_id : str | None
        A budget id explicitly supplied by the caller, or ``None`` to fall
        back to the configured default.
    settings : Settings
        The server's parsed configuration, used for its
        ``ynab_default_budget_id`` fallback.

    Returns
    -------
    str
        The budget id to use for the API call.

    Raises
    ------
    ToolError
        If ``budget_id`` is ``None`` and no default budget is configured.
    """
    if budget_id is not None:
        return budget_id
    if settings.ynab_default_budget_id is not None:
        return settings.ynab_default_budget_id
    raise ToolError(
        "No budget_id provided and YNAB_DEFAULT_BUDGET_ID is not configured."
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_client.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/client.py tests/test_client.py
git commit -m "feat: add YNAB ApiClient factory and budget-id resolution"
git push
```

---

### Task 5: `tools/budgets.py` — `list-budgets` tool

**Files:**
- Create: `src/ynab_mcp/tools/__init__.py`
- Create: `src/ynab_mcp/tools/budgets.py`
- Create: `tests/test_tools_budgets.py`

**Interfaces:**
- Consumes: `translate_api_exception` (Task 3).
- Produces: `list_budgets(client: ynab.ApiClient) -> list[ynab.PlanSummary]`, `register(mcp: FastMCP, client: ynab.ApiClient) -> None`. `register` is called by `server.py` (Task 12) only when no default budget is configured.

- [ ] **Step 1: Write the failing tests**

Create `src/ynab_mcp/tools/__init__.py`:

```python
"""Tool modules for the YNAB MCP server, one per tool group."""
```

Create `tests/test_tools_budgets.py`:

```python
"""Tests for ynab_mcp.tools.budgets."""

from types import SimpleNamespace

import ynab
from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

from ynab_mcp.tools.budgets import list_budgets


def test_list_budgets_returns_plans(mocker: MockerFixture) -> None:
    """list_budgets calls PlansApi.get_plans and returns the plan list."""
    client = mocker.Mock()
    plans_api = mocker.patch("ynab_mcp.tools.budgets.ynab.PlansApi")
    fake_plans = [SimpleNamespace(id="1", name="Family Budget")]
    plans_api.return_value.get_plans.return_value = SimpleNamespace(
        data=SimpleNamespace(plans=fake_plans)
    )

    result = list_budgets(client)

    assert result == fake_plans
    plans_api.assert_called_once_with(client)
    plans_api.return_value.get_plans.assert_called_once_with()


def test_list_budgets_raises_tool_error_on_api_exception(
    mocker: MockerFixture,
) -> None:
    """An ApiException from the SDK surfaces as a ToolError."""
    client = mocker.Mock()
    plans_api = mocker.patch("ynab_mcp.tools.budgets.ynab.PlansApi")
    plans_api.return_value.get_plans.side_effect = ynab.ApiException(
        status=401,
        reason="Unauthorized",
        body='{"error": {"id": "401", "name": "unauthorized", '
        '"detail": "Unauthorized"}}',
    )

    with raises(ToolError, match="Unauthorized"):
        list_budgets(client)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_budgets.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ynab_mcp.tools.budgets'`

- [ ] **Step 3: Write the implementation**

Create `src/ynab_mcp/tools/budgets.py`:

```python
"""list-budgets tool: enumerate the caller's YNAB budgets."""

import ynab
from fastmcp import FastMCP

from ynab_mcp.errors import translate_api_exception


def list_budgets(client: ynab.ApiClient) -> list[ynab.PlanSummary]:
    """List every YNAB budget the configured token can access.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.

    Returns
    -------
    list[ynab.PlanSummary]
        One summary per budget.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If the YNAB API request fails.
    """
    api = ynab.PlansApi(client)
    try:
        response = api.get_plans()
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return response.data.plans


def register(mcp: FastMCP, client: ynab.ApiClient) -> None:
    """Register the ``list-budgets`` tool on ``mcp``.

    Parameters
    ----------
    mcp : fastmcp.FastMCP
        The server to register the tool on.
    client : ynab.ApiClient
        A configured YNAB API client.
    """

    @mcp.tool(name="list-budgets")
    def list_budgets_tool() -> list[dict[str, object]]:
        """List every YNAB budget the configured token can access."""
        budgets = list_budgets(client)
        return [b.model_dump(mode="json") for b in budgets]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_budgets.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/tools/__init__.py src/ynab_mcp/tools/budgets.py tests/test_tools_budgets.py
git commit -m "feat: add list-budgets tool"
git push
```

---

### Task 6: `tools/accounts.py` — `list-accounts` tool

**Files:**
- Create: `src/ynab_mcp/tools/accounts.py`
- Create: `tests/test_tools_accounts.py`

**Interfaces:**
- Consumes: `resolve_budget_id` (Task 4), `translate_api_exception` (Task 3), `Settings` (Task 2).
- Produces: `list_accounts(client, budget_id) -> list[ynab.Account]`, `register(mcp, client, settings) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tools_accounts.py`:

```python
"""Tests for ynab_mcp.tools.accounts."""

from types import SimpleNamespace

import ynab
from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

from ynab_mcp.tools.accounts import list_accounts


def test_list_accounts_returns_accounts_for_budget(mocker: MockerFixture) -> None:
    """list_accounts calls AccountsApi.get_accounts with plan_id=budget_id."""
    client = mocker.Mock()
    accounts_api = mocker.patch("ynab_mcp.tools.accounts.ynab.AccountsApi")
    fake_accounts = [SimpleNamespace(id="a1", name="Checking")]
    accounts_api.return_value.get_accounts.return_value = SimpleNamespace(
        data=SimpleNamespace(accounts=fake_accounts)
    )

    result = list_accounts(client, "budget-1")

    assert result == fake_accounts
    accounts_api.return_value.get_accounts.assert_called_once_with(
        plan_id="budget-1"
    )


def test_list_accounts_raises_tool_error_on_api_exception(
    mocker: MockerFixture,
) -> None:
    """An ApiException from the SDK surfaces as a ToolError."""
    client = mocker.Mock()
    accounts_api = mocker.patch("ynab_mcp.tools.accounts.ynab.AccountsApi")
    accounts_api.return_value.get_accounts.side_effect = ynab.ApiException(
        status=404,
        reason="Not Found",
        body='{"error": {"id": "404", "name": "not_found", '
        '"detail": "Budget not found"}}',
    )

    with raises(ToolError, match="Budget not found"):
        list_accounts(client, "missing-budget")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_accounts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ynab_mcp.tools.accounts'`

- [ ] **Step 3: Write the implementation**

Create `src/ynab_mcp/tools/accounts.py`:

```python
"""list-accounts tool: enumerate accounts in a YNAB budget."""

import ynab
from fastmcp import FastMCP

from ynab_mcp.client import resolve_budget_id
from ynab_mcp.config import Settings
from ynab_mcp.errors import translate_api_exception


def list_accounts(client: ynab.ApiClient, budget_id: str) -> list[ynab.Account]:
    """List every account in a YNAB budget.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id (translated to the SDK's ``plan_id``).

    Returns
    -------
    list[ynab.Account]
        One entry per account in the budget.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If the YNAB API request fails.
    """
    api = ynab.AccountsApi(client)
    try:
        response = api.get_accounts(plan_id=budget_id)
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return response.data.accounts


def register(mcp: FastMCP, client: ynab.ApiClient, settings: Settings) -> None:
    """Register the ``list-accounts`` tool on ``mcp``.

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

    @mcp.tool(name="list-accounts")
    def list_accounts_tool(budget_id: str | None = None) -> list[dict[str, object]]:
        """List every account in a YNAB budget.

        Parameters
        ----------
        budget_id : str | None, optional
            The YNAB budget id, by default ``None`` (falls back to
            ``YNAB_DEFAULT_BUDGET_ID``).
        """
        resolved_budget_id = resolve_budget_id(budget_id, settings)
        accounts = list_accounts(client, resolved_budget_id)
        return [a.model_dump(mode="json") for a in accounts]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_accounts.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/tools/accounts.py tests/test_tools_accounts.py
git commit -m "feat: add list-accounts tool"
git push
```

---

### Task 7: `tools/categories.py` — `list-categories` tool

**Files:**
- Create: `src/ynab_mcp/tools/categories.py`
- Create: `tests/test_tools_categories.py`

**Interfaces:**
- Consumes: `resolve_budget_id` (Task 4), `translate_api_exception` (Task 3), `Settings` (Task 2).
- Produces: `list_categories(client, budget_id) -> list[ynab.Category]` (flattened across category groups — the YNAB SDK nests categories under `category_groups`, not a flat list), `register(mcp, client, settings) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tools_categories.py`:

```python
"""Tests for ynab_mcp.tools.categories."""

from types import SimpleNamespace

import ynab
from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

from ynab_mcp.tools.categories import list_categories


def test_list_categories_flattens_category_groups(mocker: MockerFixture) -> None:
    """Categories nested under category_groups are flattened into one list."""
    client = mocker.Mock()
    categories_api = mocker.patch("ynab_mcp.tools.categories.ynab.CategoriesApi")
    group_1_categories = [SimpleNamespace(id="c1", name="Groceries")]
    group_2_categories = [SimpleNamespace(id="c2", name="Rent")]
    categories_api.return_value.get_categories.return_value = SimpleNamespace(
        data=SimpleNamespace(
            category_groups=[
                SimpleNamespace(categories=group_1_categories),
                SimpleNamespace(categories=group_2_categories),
            ]
        )
    )

    result = list_categories(client, "budget-1")

    assert result == group_1_categories + group_2_categories
    categories_api.return_value.get_categories.assert_called_once_with(
        plan_id="budget-1"
    )


def test_list_categories_raises_tool_error_on_api_exception(
    mocker: MockerFixture,
) -> None:
    """An ApiException from the SDK surfaces as a ToolError."""
    client = mocker.Mock()
    categories_api = mocker.patch("ynab_mcp.tools.categories.ynab.CategoriesApi")
    categories_api.return_value.get_categories.side_effect = ynab.ApiException(
        status=404,
        reason="Not Found",
        body='{"error": {"id": "404", "name": "not_found", '
        '"detail": "Budget not found"}}',
    )

    with raises(ToolError, match="Budget not found"):
        list_categories(client, "missing-budget")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_categories.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ynab_mcp.tools.categories'`

- [ ] **Step 3: Write the implementation**

Create `src/ynab_mcp/tools/categories.py`:

```python
"""list-categories tool: enumerate categories in a YNAB budget."""

import ynab
from fastmcp import FastMCP

from ynab_mcp.client import resolve_budget_id
from ynab_mcp.config import Settings
from ynab_mcp.errors import translate_api_exception


def list_categories(client: ynab.ApiClient, budget_id: str) -> list[ynab.Category]:
    """List every category in a YNAB budget, flattened across category groups.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id (translated to the SDK's ``plan_id``).

    Returns
    -------
    list[ynab.Category]
        Every category across every category group. Each entry carries its
        own ``category_group_name``, so the flattening loses no context.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If the YNAB API request fails.
    """
    api = ynab.CategoriesApi(client)
    try:
        response = api.get_categories(plan_id=budget_id)
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return [
        category
        for group in response.data.category_groups
        for category in group.categories
    ]


def register(mcp: FastMCP, client: ynab.ApiClient, settings: Settings) -> None:
    """Register the ``list-categories`` tool on ``mcp``.

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

    @mcp.tool(name="list-categories")
    def list_categories_tool(
        budget_id: str | None = None,
    ) -> list[dict[str, object]]:
        """List every category in a YNAB budget.

        Parameters
        ----------
        budget_id : str | None, optional
            The YNAB budget id, by default ``None`` (falls back to
            ``YNAB_DEFAULT_BUDGET_ID``).
        """
        resolved_budget_id = resolve_budget_id(budget_id, settings)
        categories = list_categories(client, resolved_budget_id)
        return [c.model_dump(mode="json") for c in categories]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_categories.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/tools/categories.py tests/test_tools_categories.py
git commit -m "feat: add list-categories tool"
git push
```

---

### Task 8: `tools/payees.py` — `list-payees` tool

**Files:**
- Create: `src/ynab_mcp/tools/payees.py`
- Create: `tests/test_tools_payees.py`

**Interfaces:**
- Consumes: `resolve_budget_id` (Task 4), `translate_api_exception` (Task 3), `Settings` (Task 2).
- Produces: `list_payees(client, budget_id) -> list[ynab.Payee]`, `register(mcp, client, settings) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tools_payees.py`:

```python
"""Tests for ynab_mcp.tools.payees."""

from types import SimpleNamespace

import ynab
from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

from ynab_mcp.tools.payees import list_payees


def test_list_payees_returns_payees_for_budget(mocker: MockerFixture) -> None:
    """list_payees calls PayeesApi.get_payees with plan_id=budget_id."""
    client = mocker.Mock()
    payees_api = mocker.patch("ynab_mcp.tools.payees.ynab.PayeesApi")
    fake_payees = [SimpleNamespace(id="p1", name="Amazon")]
    payees_api.return_value.get_payees.return_value = SimpleNamespace(
        data=SimpleNamespace(payees=fake_payees)
    )

    result = list_payees(client, "budget-1")

    assert result == fake_payees
    payees_api.return_value.get_payees.assert_called_once_with(plan_id="budget-1")


def test_list_payees_raises_tool_error_on_api_exception(
    mocker: MockerFixture,
) -> None:
    """An ApiException from the SDK surfaces as a ToolError."""
    client = mocker.Mock()
    payees_api = mocker.patch("ynab_mcp.tools.payees.ynab.PayeesApi")
    payees_api.return_value.get_payees.side_effect = ynab.ApiException(
        status=404,
        reason="Not Found",
        body='{"error": {"id": "404", "name": "not_found", '
        '"detail": "Budget not found"}}',
    )

    with raises(ToolError, match="Budget not found"):
        list_payees(client, "missing-budget")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_payees.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ynab_mcp.tools.payees'`

- [ ] **Step 3: Write the implementation**

Create `src/ynab_mcp/tools/payees.py`:

```python
"""list-payees tool: enumerate payees in a YNAB budget."""

import ynab
from fastmcp import FastMCP

from ynab_mcp.client import resolve_budget_id
from ynab_mcp.config import Settings
from ynab_mcp.errors import translate_api_exception


def list_payees(client: ynab.ApiClient, budget_id: str) -> list[ynab.Payee]:
    """List every payee in a YNAB budget.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id (translated to the SDK's ``plan_id``).

    Returns
    -------
    list[ynab.Payee]
        One entry per payee in the budget.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If the YNAB API request fails.
    """
    api = ynab.PayeesApi(client)
    try:
        response = api.get_payees(plan_id=budget_id)
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return response.data.payees


def register(mcp: FastMCP, client: ynab.ApiClient, settings: Settings) -> None:
    """Register the ``list-payees`` tool on ``mcp``.

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

    @mcp.tool(name="list-payees")
    def list_payees_tool(budget_id: str | None = None) -> list[dict[str, object]]:
        """List every payee in a YNAB budget.

        Parameters
        ----------
        budget_id : str | None, optional
            The YNAB budget id, by default ``None`` (falls back to
            ``YNAB_DEFAULT_BUDGET_ID``).
        """
        resolved_budget_id = resolve_budget_id(budget_id, settings)
        payees = list_payees(client, resolved_budget_id)
        return [p.model_dump(mode="json") for p in payees]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_payees.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/tools/payees.py tests/test_tools_payees.py
git commit -m "feat: add list-payees tool"
git push
```

---

### Task 9: `tools/months.py` — `get-month-info` tool + shared month parsing

**Files:**
- Create: `src/ynab_mcp/tools/months.py`
- Create: `tests/test_tools_months.py`

**Interfaces:**
- Consumes: `resolve_budget_id` (Task 4), `translate_api_exception` (Task 3), `Settings` (Task 2).
- Produces: `parse_month(value: str) -> datetime.date` (reused by `tools/lookup.py` in Task 11 — import as `from ynab_mcp.tools.months import parse_month`), `get_month_info(client, budget_id, month) -> ynab.MonthDetail`, `register(mcp, client, settings) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tools_months.py`:

```python
"""Tests for ynab_mcp.tools.months."""

from datetime import date
from types import SimpleNamespace

import ynab
from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

from ynab_mcp.tools.months import get_month_info, parse_month


def test_parse_month_accepts_iso_date() -> None:
    """An ISO date string parses to the matching date."""
    assert parse_month("2024-03-01") == date(2024, 3, 1)


def test_parse_month_accepts_current() -> None:
    """The literal 'current' resolves to the first of this month."""
    result = parse_month("current")

    assert result == date.today().replace(day=1)


def test_parse_month_rejects_invalid_value() -> None:
    """An unparseable month string raises a ToolError with a hint."""
    with raises(ToolError, match="Invalid month"):
        parse_month("not-a-date")


def test_get_month_info_returns_month_detail(mocker: MockerFixture) -> None:
    """get_month_info calls MonthsApi.get_plan_month with the parsed month."""
    client = mocker.Mock()
    months_api = mocker.patch("ynab_mcp.tools.months.ynab.MonthsApi")
    fake_month = SimpleNamespace(month=date(2024, 3, 1), budgeted=100000)
    months_api.return_value.get_plan_month.return_value = SimpleNamespace(
        data=SimpleNamespace(month=fake_month)
    )

    result = get_month_info(client, "budget-1", "2024-03-01")

    assert result == fake_month
    months_api.return_value.get_plan_month.assert_called_once_with(
        plan_id="budget-1", month=date(2024, 3, 1)
    )


def test_get_month_info_raises_tool_error_on_api_exception(
    mocker: MockerFixture,
) -> None:
    """An ApiException from the SDK surfaces as a ToolError."""
    client = mocker.Mock()
    months_api = mocker.patch("ynab_mcp.tools.months.ynab.MonthsApi")
    months_api.return_value.get_plan_month.side_effect = ynab.ApiException(
        status=404,
        reason="Not Found",
        body='{"error": {"id": "404", "name": "not_found", '
        '"detail": "Budget not found"}}',
    )

    with raises(ToolError, match="Budget not found"):
        get_month_info(client, "missing-budget", "2024-03-01")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_months.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ynab_mcp.tools.months'`

- [ ] **Step 3: Write the implementation**

Create `src/ynab_mcp/tools/months.py`:

```python
"""get-month-info tool: fetch YNAB budget totals for a single month."""

from datetime import date

import ynab
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from ynab_mcp.client import resolve_budget_id
from ynab_mcp.config import Settings
from ynab_mcp.errors import translate_api_exception


def parse_month(value: str) -> date:
    """Parse a YNAB month value into a ``datetime.date``.

    Parameters
    ----------
    value : str
        An ISO-formatted month (e.g. ``"2024-01-01"``) or the literal
        string ``"current"`` for the current calendar month (UTC).

    Returns
    -------
    datetime.date
        The first day of the resolved month.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If ``value`` is not a valid ISO date and not ``"current"``.
    """
    if value == "current":
        return date.today().replace(day=1)
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ToolError(
            f"Invalid month {value!r}: expected an ISO date (YYYY-MM-DD) or "
            "'current'."
        ) from exc


def get_month_info(
    client: ynab.ApiClient, budget_id: str, month: str
) -> ynab.MonthDetail:
    """Get YNAB budget totals and category detail for a single month.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id (translated to the SDK's ``plan_id``).
    month : str
        An ISO-formatted month (e.g. ``"2024-01-01"``) or the literal
        string ``"current"``.

    Returns
    -------
    ynab.MonthDetail
        Budget totals and category detail for the month.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If ``month`` is invalid, or if the YNAB API request fails.
    """
    resolved_month = parse_month(month)
    api = ynab.MonthsApi(client)
    try:
        response = api.get_plan_month(plan_id=budget_id, month=resolved_month)
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return response.data.month


def register(mcp: FastMCP, client: ynab.ApiClient, settings: Settings) -> None:
    """Register the ``get-month-info`` tool on ``mcp``.

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

    @mcp.tool(name="get-month-info")
    def get_month_info_tool(
        month: str, budget_id: str | None = None
    ) -> dict[str, object]:
        """Get YNAB budget totals and category detail for a single month.

        Parameters
        ----------
        month : str
            An ISO-formatted month (e.g. ``"2024-01-01"``) or the literal
            string ``"current"``.
        budget_id : str | None, optional
            The YNAB budget id, by default ``None`` (falls back to
            ``YNAB_DEFAULT_BUDGET_ID``).
        """
        resolved_budget_id = resolve_budget_id(budget_id, settings)
        month_info = get_month_info(client, resolved_budget_id, month)
        return month_info.model_dump(mode="json")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_months.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/tools/months.py tests/test_tools_months.py
git commit -m "feat: add get-month-info tool"
git push
```

---

### Task 10: `tools/transactions.py` — `list-transactions` tool

**Files:**
- Create: `src/ynab_mcp/tools/transactions.py`
- Create: `tests/test_tools_transactions.py`

**Interfaces:**
- Consumes: `resolve_budget_id` (Task 4), `translate_api_exception` (Task 3), `Settings` (Task 2).
- Produces: `list_transactions(client, budget_id, account_id=None, category_id=None, payee_id=None, since_date=None, until_date=None) -> list[ynab.TransactionDetail]`, `register(mcp, client, settings) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tools_transactions.py`:

```python
"""Tests for ynab_mcp.tools.transactions."""

from datetime import date
from types import SimpleNamespace

import ynab
from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

from ynab_mcp.tools.transactions import list_transactions


def test_list_transactions_with_no_filters_calls_get_transactions(
    mocker: MockerFixture,
) -> None:
    """No entity filter dispatches to the plain get_transactions endpoint."""
    client = mocker.Mock()
    transactions_api = mocker.patch(
        "ynab_mcp.tools.transactions.ynab.TransactionsApi"
    )
    fake_transactions = [SimpleNamespace(id="t1")]
    transactions_api.return_value.get_transactions.return_value = SimpleNamespace(
        data=SimpleNamespace(transactions=fake_transactions)
    )

    result = list_transactions(client, "budget-1")

    assert result == fake_transactions
    transactions_api.return_value.get_transactions.assert_called_once_with(
        plan_id="budget-1", since_date=None, until_date=None
    )


def test_list_transactions_with_account_id_calls_get_transactions_by_account(
    mocker: MockerFixture,
) -> None:
    """account_id dispatches to get_transactions_by_account."""
    client = mocker.Mock()
    transactions_api = mocker.patch(
        "ynab_mcp.tools.transactions.ynab.TransactionsApi"
    )
    fake_transactions = [SimpleNamespace(id="t1")]
    transactions_api.return_value.get_transactions_by_account.return_value = (
        SimpleNamespace(data=SimpleNamespace(transactions=fake_transactions))
    )

    result = list_transactions(
        client,
        "budget-1",
        account_id="acct-1",
        since_date=date(2024, 1, 1),
        until_date=date(2024, 2, 1),
    )

    assert result == fake_transactions
    transactions_api.return_value.get_transactions_by_account.assert_called_once_with(
        plan_id="budget-1",
        account_id="acct-1",
        since_date=date(2024, 1, 1),
        until_date=date(2024, 2, 1),
    )


def test_list_transactions_with_category_id_calls_get_transactions_by_category(
    mocker: MockerFixture,
) -> None:
    """category_id dispatches to get_transactions_by_category."""
    client = mocker.Mock()
    transactions_api = mocker.patch(
        "ynab_mcp.tools.transactions.ynab.TransactionsApi"
    )
    fake_transactions = [SimpleNamespace(id="t1")]
    transactions_api.return_value.get_transactions_by_category.return_value = (
        SimpleNamespace(data=SimpleNamespace(transactions=fake_transactions))
    )

    result = list_transactions(client, "budget-1", category_id="cat-1")

    assert result == fake_transactions
    transactions_api.return_value.get_transactions_by_category.assert_called_once_with(
        plan_id="budget-1", category_id="cat-1", since_date=None, until_date=None
    )


def test_list_transactions_with_payee_id_calls_get_transactions_by_payee(
    mocker: MockerFixture,
) -> None:
    """payee_id dispatches to get_transactions_by_payee."""
    client = mocker.Mock()
    transactions_api = mocker.patch(
        "ynab_mcp.tools.transactions.ynab.TransactionsApi"
    )
    fake_transactions = [SimpleNamespace(id="t1")]
    transactions_api.return_value.get_transactions_by_payee.return_value = (
        SimpleNamespace(data=SimpleNamespace(transactions=fake_transactions))
    )

    result = list_transactions(client, "budget-1", payee_id="payee-1")

    assert result == fake_transactions
    transactions_api.return_value.get_transactions_by_payee.assert_called_once_with(
        plan_id="budget-1", payee_id="payee-1", since_date=None, until_date=None
    )


def test_list_transactions_rejects_multiple_entity_filters(
    mocker: MockerFixture,
) -> None:
    """Passing more than one of account_id/category_id/payee_id is an error."""
    client = mocker.Mock()

    with raises(ToolError, match="at most one"):
        list_transactions(
            client, "budget-1", account_id="acct-1", category_id="cat-1"
        )


def test_list_transactions_raises_tool_error_on_api_exception(
    mocker: MockerFixture,
) -> None:
    """An ApiException from the SDK surfaces as a ToolError."""
    client = mocker.Mock()
    transactions_api = mocker.patch(
        "ynab_mcp.tools.transactions.ynab.TransactionsApi"
    )
    transactions_api.return_value.get_transactions.side_effect = ynab.ApiException(
        status=404,
        reason="Not Found",
        body='{"error": {"id": "404", "name": "not_found", '
        '"detail": "Budget not found"}}',
    )

    with raises(ToolError, match="Budget not found"):
        list_transactions(client, "missing-budget")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_transactions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ynab_mcp.tools.transactions'`

- [ ] **Step 3: Write the implementation**

Create `src/ynab_mcp/tools/transactions.py`:

```python
"""list-transactions tool: enumerate transactions in a YNAB budget."""

from datetime import date

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
            response = api.get_transactions_by_account(
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
    return response.data.transactions


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_transactions.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/tools/transactions.py tests/test_tools_transactions.py
git commit -m "feat: add list-transactions tool"
git push
```

---

### Task 11: `tools/lookup.py` — `lookup-entity-by-id` tool

**Files:**
- Create: `src/ynab_mcp/tools/lookup.py`
- Create: `tests/test_tools_lookup.py`

**Interfaces:**
- Consumes: `resolve_budget_id` (Task 4), `translate_api_exception` (Task 3), `Settings` (Task 2), `parse_month` (Task 9).
- Produces: `lookup_entity_by_id(client, budget_id, entity_type, entity_id) -> ynab.Account | ynab.Category | ynab.Payee | ynab.TransactionDetail | ynab.MonthDetail`, `register(mcp, client, settings) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tools_lookup.py`:

```python
"""Tests for ynab_mcp.tools.lookup."""

from datetime import date
from types import SimpleNamespace

import ynab
from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

from ynab_mcp.tools.lookup import lookup_entity_by_id


def test_lookup_account_calls_get_account_by_id(mocker: MockerFixture) -> None:
    """entity_type='account' dispatches to AccountsApi.get_account_by_id."""
    client = mocker.Mock()
    accounts_api = mocker.patch("ynab_mcp.tools.lookup.ynab.AccountsApi")
    fake_account = SimpleNamespace(id="a1", name="Checking")
    accounts_api.return_value.get_account_by_id.return_value = SimpleNamespace(
        data=SimpleNamespace(account=fake_account)
    )

    result = lookup_entity_by_id(client, "budget-1", "account", "a1")

    assert result == fake_account
    accounts_api.return_value.get_account_by_id.assert_called_once_with(
        plan_id="budget-1", account_id="a1"
    )


def test_lookup_category_calls_get_category_by_id(mocker: MockerFixture) -> None:
    """entity_type='category' dispatches to CategoriesApi.get_category_by_id."""
    client = mocker.Mock()
    categories_api = mocker.patch("ynab_mcp.tools.lookup.ynab.CategoriesApi")
    fake_category = SimpleNamespace(id="c1", name="Groceries")
    categories_api.return_value.get_category_by_id.return_value = SimpleNamespace(
        data=SimpleNamespace(category=fake_category)
    )

    result = lookup_entity_by_id(client, "budget-1", "category", "c1")

    assert result == fake_category
    categories_api.return_value.get_category_by_id.assert_called_once_with(
        plan_id="budget-1", category_id="c1"
    )


def test_lookup_payee_calls_get_payee_by_id(mocker: MockerFixture) -> None:
    """entity_type='payee' dispatches to PayeesApi.get_payee_by_id."""
    client = mocker.Mock()
    payees_api = mocker.patch("ynab_mcp.tools.lookup.ynab.PayeesApi")
    fake_payee = SimpleNamespace(id="p1", name="Amazon")
    payees_api.return_value.get_payee_by_id.return_value = SimpleNamespace(
        data=SimpleNamespace(payee=fake_payee)
    )

    result = lookup_entity_by_id(client, "budget-1", "payee", "p1")

    assert result == fake_payee
    payees_api.return_value.get_payee_by_id.assert_called_once_with(
        plan_id="budget-1", payee_id="p1"
    )


def test_lookup_transaction_calls_get_transaction_by_id(
    mocker: MockerFixture,
) -> None:
    """entity_type='transaction' dispatches to TransactionsApi.get_transaction_by_id."""
    client = mocker.Mock()
    transactions_api = mocker.patch("ynab_mcp.tools.lookup.ynab.TransactionsApi")
    fake_transaction = SimpleNamespace(id="t1")
    transactions_api.return_value.get_transaction_by_id.return_value = (
        SimpleNamespace(data=SimpleNamespace(transaction=fake_transaction))
    )

    result = lookup_entity_by_id(client, "budget-1", "transaction", "t1")

    assert result == fake_transaction
    transactions_api.return_value.get_transaction_by_id.assert_called_once_with(
        plan_id="budget-1", transaction_id="t1"
    )


def test_lookup_month_calls_get_plan_month(mocker: MockerFixture) -> None:
    """entity_type='month' parses entity_id and dispatches to get_plan_month."""
    client = mocker.Mock()
    months_api = mocker.patch("ynab_mcp.tools.lookup.ynab.MonthsApi")
    fake_month = SimpleNamespace(month=date(2024, 3, 1))
    months_api.return_value.get_plan_month.return_value = SimpleNamespace(
        data=SimpleNamespace(month=fake_month)
    )

    result = lookup_entity_by_id(client, "budget-1", "month", "2024-03-01")

    assert result == fake_month
    months_api.return_value.get_plan_month.assert_called_once_with(
        plan_id="budget-1", month=date(2024, 3, 1)
    )


def test_lookup_rejects_unknown_entity_type(mocker: MockerFixture) -> None:
    """An entity_type outside the known set raises a ToolError."""
    client = mocker.Mock()

    with raises(ToolError, match="Unknown entity_type"):
        lookup_entity_by_id(client, "budget-1", "invoice", "x1")  # type: ignore[arg-type]


def test_lookup_raises_tool_error_on_api_exception(mocker: MockerFixture) -> None:
    """An ApiException from the SDK surfaces as a ToolError."""
    client = mocker.Mock()
    accounts_api = mocker.patch("ynab_mcp.tools.lookup.ynab.AccountsApi")
    accounts_api.return_value.get_account_by_id.side_effect = ynab.ApiException(
        status=404,
        reason="Not Found",
        body='{"error": {"id": "404", "name": "not_found", '
        '"detail": "Account not found"}}',
    )

    with raises(ToolError, match="Account not found"):
        lookup_entity_by_id(client, "budget-1", "account", "missing")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_lookup.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ynab_mcp.tools.lookup'`

- [ ] **Step 3: Write the implementation**

Create `src/ynab_mcp/tools/lookup.py`:

```python
"""lookup-entity-by-id tool: fetch a single YNAB entity of any known type."""

from typing import Literal

import ynab
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from ynab_mcp.client import resolve_budget_id
from ynab_mcp.config import Settings
from ynab_mcp.errors import translate_api_exception
from ynab_mcp.tools.months import parse_month

EntityType = Literal["account", "category", "payee", "transaction", "month"]

_KNOWN_ENTITY_TYPES = "account, category, payee, transaction, month"


def lookup_entity_by_id(
    client: ynab.ApiClient, budget_id: str, entity_type: EntityType, entity_id: str
) -> (
    ynab.Account
    | ynab.Category
    | ynab.Payee
    | ynab.TransactionDetail
    | ynab.MonthDetail
):
    """Fetch a single YNAB entity by its id.

    Parameters
    ----------
    client : ynab.ApiClient
        A configured YNAB API client.
    budget_id : str
        The YNAB budget id (translated to the SDK's ``plan_id``).
    entity_type : {"account", "category", "payee", "transaction", "month"}
        Which kind of entity ``entity_id`` refers to.
    entity_id : str
        The entity's id. For ``entity_type="month"`` this is an ISO date
        (e.g. ``"2024-01-01"``) or the literal ``"current"``, not a UUID.

    Returns
    -------
    ynab.Account | ynab.Category | ynab.Payee | ynab.TransactionDetail | ynab.MonthDetail
        The resolved entity.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If ``entity_type`` is not one of the known values, if ``entity_id``
        is an invalid month value, or if the YNAB API request fails.
    """
    try:
        if entity_type == "account":
            result = (
                ynab.AccountsApi(client)
                .get_account_by_id(plan_id=budget_id, account_id=entity_id)
                .data.account
            )
        elif entity_type == "category":
            result = (
                ynab.CategoriesApi(client)
                .get_category_by_id(plan_id=budget_id, category_id=entity_id)
                .data.category
            )
        elif entity_type == "payee":
            result = (
                ynab.PayeesApi(client)
                .get_payee_by_id(plan_id=budget_id, payee_id=entity_id)
                .data.payee
            )
        elif entity_type == "transaction":
            result = (
                ynab.TransactionsApi(client)
                .get_transaction_by_id(plan_id=budget_id, transaction_id=entity_id)
                .data.transaction
            )
        elif entity_type == "month":
            resolved_month = parse_month(entity_id)
            result = (
                ynab.MonthsApi(client)
                .get_plan_month(plan_id=budget_id, month=resolved_month)
                .data.month
            )
        else:
            raise ToolError(
                f"Unknown entity_type {entity_type!r}. Expected one of: "
                f"{_KNOWN_ENTITY_TYPES}."
            )
    except ynab.ApiException as exc:
        raise translate_api_exception(exc) from exc
    return result


def register(mcp: FastMCP, client: ynab.ApiClient, settings: Settings) -> None:
    """Register the ``lookup-entity-by-id`` tool on ``mcp``.

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

    @mcp.tool(name="lookup-entity-by-id")
    def lookup_entity_by_id_tool(
        entity_type: EntityType, entity_id: str, budget_id: str | None = None
    ) -> dict[str, object]:
        """Fetch a single YNAB entity by its id.

        Parameters
        ----------
        entity_type : {"account", "category", "payee", "transaction", "month"}
            Which kind of entity ``entity_id`` refers to.
        entity_id : str
            The entity's id. For ``entity_type="month"`` this is an ISO
            date (e.g. ``"2024-01-01"``) or the literal ``"current"``.
        budget_id : str | None, optional
            The YNAB budget id, by default ``None`` (falls back to
            ``YNAB_DEFAULT_BUDGET_ID``).
        """
        resolved_budget_id = resolve_budget_id(budget_id, settings)
        entity = lookup_entity_by_id(
            client, resolved_budget_id, entity_type, entity_id
        )
        return entity.model_dump(mode="json")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_lookup.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/ynab_mcp/tools/lookup.py tests/test_tools_lookup.py
git commit -m "feat: add lookup-entity-by-id tool"
git push
```

---

### Task 12: `server.py` — wire the FastMCP server + docs

**Files:**
- Create: `src/ynab_mcp/server.py`
- Create: `tests/test_server.py`
- Modify: `pyproject.toml`
- Modify: `README.md`

**Interfaces:**
- Consumes: `build_api_client` (Task 4), `Settings` (Task 2), every `tools/*.register` (Tasks 5-11).
- Produces: `build_server() -> FastMCP`, `main() -> None` (the `uv run ynab-mcp` entry point). This is the final task — after it, `make pr_check` must pass end to end.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_server.py`:

```python
"""Tests for ynab_mcp.server."""

import asyncio

import pytest
from fastmcp import Client, FastMCP

from ynab_mcp.server import build_server


def _list_tool_names(mcp: FastMCP) -> set[str]:
    """Return the set of tool names registered on a built server.

    Parameters
    ----------
    mcp : fastmcp.FastMCP
        A server built by ``build_server``.

    Returns
    -------
    set[str]
        Every registered tool's name.
    """

    async def _list() -> set[str]:
        async with Client(mcp) as client:
            tools = await client.list_tools()
            return {tool.name for tool in tools}

    return asyncio.run(_list())


def test_build_server_raises_without_pat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Building the server fails hard when YNAB_PAT is unset."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("YNAB_PAT", raising=False)

    with pytest.raises(RuntimeError, match="YNAB_PAT"):
        build_server()


def test_build_server_includes_list_budgets_without_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """list-budgets is registered when no default budget is configured."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("YNAB_PAT", "test-token")
    monkeypatch.delenv("YNAB_DEFAULT_BUDGET_ID", raising=False)

    mcp = build_server()

    tool_names = _list_tool_names(mcp)
    assert "list-budgets" in tool_names


def test_build_server_hides_list_budgets_with_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """list-budgets is hidden when a default budget is configured."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("YNAB_PAT", "test-token")
    monkeypatch.setenv("YNAB_DEFAULT_BUDGET_ID", "budget-123")

    mcp = build_server()

    tool_names = _list_tool_names(mcp)
    assert "list-budgets" not in tool_names


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
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ynab_mcp.server'`

- [ ] **Step 3: Write the implementation**

Create `src/ynab_mcp/server.py`:

```python
"""FastMCP stdio server exposing read-only YNAB data."""

from fastmcp import FastMCP

from ynab_mcp.client import build_api_client
from ynab_mcp.config import Settings
from ynab_mcp.tools import (
    accounts,
    budgets,
    categories,
    lookup,
    months,
    payees,
    transactions,
)


def build_server() -> FastMCP:
    """Build and wire the YNAB MCP server.

    Reads configuration from the environment, constructs a shared YNAB API
    client, and registers every read-only tool. ``list-budgets`` is
    registered only when no default budget is configured.

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

    return mcp


def main() -> None:
    """Build and run the YNAB MCP server over stdio."""
    build_server().run()


if __name__ == "__main__":
    main()
```

In `pyproject.toml`, add a script entry point right after the `[project]` table's `dependencies` block:

```toml
[project.scripts]
ynab-mcp = "ynab_mcp.server:main"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv sync --dev && uv run pytest tests/test_server.py -v`
Expected: 4 passed

- [ ] **Step 5: Update README.md with setup + run instructions**

Replace the full contents of `README.md`:

```markdown
# ynab-mcp

MCP server for YNAB

Python backend managed with `uv`. Run `make deps` then `make pr_check`.

## Setup

1. Copy `.env.example` to `.env` and set `YNAB_PAT` to a YNAB personal
   access token (https://api.ynab.com/#personal-access-tokens).
2. Optionally set `YNAB_DEFAULT_BUDGET_ID` to skip passing a budget id to
   every tool call (this also hides the `list-budgets` tool, since there's
   only one budget context).

## Running

```bash
uv run ynab-mcp
```

This starts the MCP server over stdio. To exercise it with
[MCP Inspector](https://github.com/modelcontextprotocol/inspector):

```bash
npx @modelcontextprotocol/inspector uv run ynab-mcp
```

## Tools

Read-only tools, backed by the official `ynab` PyPI client:

- `list-budgets` — every budget the token can access (hidden when
  `YNAB_DEFAULT_BUDGET_ID` is set).
- `list-accounts`, `list-categories`, `list-payees` — enumerate entities in
  a budget.
- `list-transactions` — filterable by account, category, payee, and/or
  date range.
- `get-month-info` — budget totals and category detail for a month.
- `lookup-entity-by-id` — fetch a single account/category/payee/
  transaction/month by id.

Write/mutation tools are out of scope for this server (a follow-up card).
```

- [ ] **Step 6: Run the full quality gate**

Run: `make pr_check`
Expected: `make lint` (black --check + ruff + mypy) and `make tests` (pytest) both exit 0 with no errors.

Run: `make coverage`
Expected: exits 0, coverage >= 80%.

- [ ] **Step 7: Commit**

```bash
git add src/ynab_mcp/server.py tests/test_server.py pyproject.toml README.md
git commit -m "feat: wire the YNAB MCP server and add uv run ynab-mcp entry point"
git push
```

---

## Self-Review Notes

- **Spec coverage:** every design-doc section has a task — terminology decision (Global Constraints + `client.py` in Task 4), module layout (Tasks 1, 5-12), config (Task 2), client + budget resolution (Task 4), error handling (Task 3), all seven tools (Tasks 5-11), server wiring (Task 12), testing strategy (a task per module, mocked `ynab.*Api`), `.env.example` (Task 2), out-of-scope write tools (not built, per Global Constraints).
- **Placeholder scan:** no TBD/TODO; every step has complete, runnable code.
- **Type consistency:** `resolve_budget_id(budget_id: str | None, settings: Settings) -> str` (Task 4) is called identically in every tool wrapper (Tasks 6-11) with the same parameter order. `parse_month(value: str) -> date` (Task 9) is imported and called identically in `lookup.py` (Task 11). `translate_api_exception(exc: ynab.ApiException) -> ToolError` (Task 3) signature matches every `except ynab.ApiException as exc: raise translate_api_exception(exc) from exc` call site.
