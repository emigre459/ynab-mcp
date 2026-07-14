"""E2E: the real `uv run ynab-mcp` stdio server speaks MCP correctly."""

import asyncio

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport


@pytest.mark.e2e
def test_uv_run_ynab_mcp_stdio_server_lists_expected_tools() -> None:
    """The real stdio subprocess launches and lists all 8 read-only tools.

    Uses a dummy YNAB_PAT: listing tools never calls the YNAB API, so no
    live credentials are needed for this smoke check. YNAB_DEFAULT_BUDGET_ID
    is explicitly cleared so a developer's local .env (which may set a real
    default budget) can't hide list-budgets and break this assertion --
    load_dotenv() never overrides an already-set environment variable, even
    an empty one.
    """
    transport = StdioTransport(
        command="uv",
        args=["run", "ynab-mcp"],
        env={"YNAB_PAT": "e2e-dummy-token", "YNAB_DEFAULT_BUDGET_ID": ""},
    )

    async def _list_tool_names() -> set[str]:
        async with Client(transport) as client:
            tools = await client.list_tools()
            return {tool.name for tool in tools}

    tool_names = asyncio.run(_list_tool_names())

    assert tool_names == {
        "list-budgets",
        "list-accounts",
        "list-categories",
        "list-transactions",
        "get-month-info",
        "list-payees",
        "lookup-entity-by-id",
        "find-payee-transactions",
    }
