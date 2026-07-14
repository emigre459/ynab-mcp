"""Tests for ynab_mcp.server."""

import asyncio

import pytest
from amazonorders.exception import AmazonOrdersAuthError
from fastmcp import Client, FastMCP
from pytest_mock import MockerFixture

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


def test_build_server_registers_find_amazon_transactions_when_configured(
    monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
) -> None:
    """The Amazon tool is registered when login() succeeds at startup."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("YNAB_PAT", "test-token")
    monkeypatch.setenv("YNAB_DEFAULT_BUDGET_ID", "budget-123")
    monkeypatch.setenv("AMAZON_USERNAME", "user@example.com")
    monkeypatch.setenv("AMAZON_PASSWORD", "hunter2")
    monkeypatch.delenv("AMAZON_OTP_SECRET_KEY", raising=False)
    build_amazon_session = mocker.patch("ynab_mcp.server.build_amazon_session")
    mocker.patch("ynab_mcp.server.build_amazon_orders")
    mocker.patch("ynab_mcp.server.build_amazon_transactions")

    mcp = build_server()

    tool_names = _list_tool_names(mcp)
    assert "find-amazon-transactions" in tool_names
    build_amazon_session.return_value.login.assert_called_once_with()


def test_build_server_omits_find_amazon_transactions_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Amazon tool is absent when Amazon credentials are unset."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("YNAB_PAT", "test-token")
    monkeypatch.setenv("YNAB_DEFAULT_BUDGET_ID", "budget-123")
    monkeypatch.delenv("AMAZON_USERNAME", raising=False)
    monkeypatch.delenv("AMAZON_PASSWORD", raising=False)

    mcp = build_server()

    tool_names = _list_tool_names(mcp)
    assert "find-amazon-transactions" not in tool_names


def test_build_server_omits_find_amazon_transactions_when_login_fails(
    monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
) -> None:
    """A session that can't authenticate at startup doesn't register the tool.

    Fail-soft, matching the "Amazon unconfigured" case: a broken/expired
    Amazon session shouldn't take down the whole YNAB server, just disable
    the Amazon tool for this run.
    """
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("YNAB_PAT", "test-token")
    monkeypatch.setenv("YNAB_DEFAULT_BUDGET_ID", "budget-123")
    monkeypatch.setenv("AMAZON_USERNAME", "user@example.com")
    monkeypatch.setenv("AMAZON_PASSWORD", "hunter2")
    monkeypatch.delenv("AMAZON_OTP_SECRET_KEY", raising=False)
    build_amazon_session = mocker.patch("ynab_mcp.server.build_amazon_session")
    build_amazon_session.return_value.login.side_effect = AmazonOrdersAuthError(
        "session expired"
    )
    mocker.patch("ynab_mcp.server.build_amazon_orders")
    mocker.patch("ynab_mcp.server.build_amazon_transactions")

    mcp = build_server()

    tool_names = _list_tool_names(mcp)
    assert "find-amazon-transactions" not in tool_names
