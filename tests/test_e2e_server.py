"""E2E: the real `uv run ynab-mcp` stdio server speaks MCP correctly."""

import asyncio

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport


async def _list_tool_names(transport: StdioTransport) -> set[str]:
    """List every tool name the real stdio subprocess exposes.

    Parameters
    ----------
    transport : fastmcp.client.transports.StdioTransport
        A transport for the real `uv run ynab-mcp` subprocess.

    Returns
    -------
    set[str]
        Every registered tool's name.
    """
    async with Client(transport) as client:
        tools = await client.list_tools()
        return {tool.name for tool in tools}


@pytest.mark.e2e
def test_uv_run_ynab_mcp_stdio_server_lists_expected_tools() -> None:
    """The real stdio subprocess launches and lists all 7 read-only tools.

    Uses a dummy YNAB_PAT: listing tools never calls the YNAB API, so no
    live credentials are needed for this smoke check. YNAB_DEFAULT_BUDGET_ID
    and the AMAZON_* vars are explicitly cleared so a developer's local .env
    (which may set a real default budget or Amazon credentials) can't change
    the expected tool set -- load_dotenv() never overrides an already-set
    environment variable, even an empty one.
    """
    transport = StdioTransport(
        command="uv",
        args=["run", "ynab-mcp"],
        env={
            "YNAB_PAT": "e2e-dummy-token",
            "YNAB_DEFAULT_BUDGET_ID": "",
            "AMAZON_USERNAME": "",
            "AMAZON_PASSWORD": "",
        },
    )

    tool_names = asyncio.run(_list_tool_names(transport))

    assert tool_names == {
        "list-budgets",
        "list-accounts",
        "list-categories",
        "list-transactions",
        "get-month-info",
        "list-payees",
        "lookup-entity-by-id",
    }


@pytest.mark.e2e
def test_uv_run_ynab_mcp_stdio_server_registers_find_amazon_transactions_when_configured() -> (
    None
):
    """The real stdio subprocess registers find-amazon-transactions too.

    Uses dummy Amazon credentials: AmazonSession's constructor makes no
    network calls (only .login(), which this server deliberately never
    calls), so listing tools stays safe with no live credentials or an
    established session. This exercises the real import graph and
    conditional-registration wiring through the actual subprocess, which
    the mocked unit tests in test_server.py cannot catch.
    """
    transport = StdioTransport(
        command="uv",
        args=["run", "ynab-mcp"],
        env={
            "YNAB_PAT": "e2e-dummy-token",
            "YNAB_DEFAULT_BUDGET_ID": "",
            "AMAZON_USERNAME": "e2e-dummy-user",
            "AMAZON_PASSWORD": "e2e-dummy-password",
        },
    )

    tool_names = asyncio.run(_list_tool_names(transport))

    assert "find-amazon-transactions" in tool_names
