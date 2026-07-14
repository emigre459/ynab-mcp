"""Tests for ynab_mcp.server."""

import asyncio

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

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
