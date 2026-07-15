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
    """The real stdio subprocess launches and lists all 14 tools.

    7 read-only + 4 write + 3 analysis tools. Uses a dummy YNAB_PAT: listing tools never calls the YNAB API, so no
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
        "bulk-manage-transactions",
        "manage-budgeted-amount",
        "manage-payees",
        "manage-scheduled-transaction",
        "find-payee-transactions",
        "flag-category-spend",
        "analyze-category-trends",
    }


# No E2E test exercises the "Amazon configured" registration path with dummy
# credentials: server.py calls the real AmazonSession.login() at startup for
# that path, and amazon-orders persists its cookie jar to a single fixed
# global path (~/.config/amazonorders/cookies.json, no env override) shared
# by every process on the machine -- including a developer's real, already
# -established session. Dummy credentials on a machine with a valid real
# session would silently "succeed" via the leftover real cookies regardless
# of the (wrong) credentials passed, making such a test non-deterministic.
# The login()-success and login()-failure registration paths are instead
# covered deterministically by the fully-mocked tests in test_server.py.
