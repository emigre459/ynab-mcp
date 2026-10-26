"""E2E: the real `uv run ynab-mcp` stdio server speaks MCP correctly."""

import asyncio

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport


async def _list_tools_and_protocol(
    transport: StdioTransport, mode: str
) -> tuple[set[str], str | None]:
    """List every tool name, and the negotiated protocol version, over stdio.

    Parameters
    ----------
    transport : fastmcp.client.transports.StdioTransport
        A transport for the real `uv run ynab-mcp` subprocess.
    mode : str
        The ``fastmcp.Client`` connect mode: ``"auto"`` negotiates the modern
        ``2026-07-28`` protocol era, ``"legacy"`` pins the handshake era.

    Returns
    -------
    tuple[set[str], str | None]
        Every registered tool's name, and the protocol version the
        connection negotiated.
    """
    async with Client(transport, mode=mode) as client:
        tools = await client.list_tools()
        return {tool.name for tool in tools}, client.protocol_version


@pytest.mark.e2e
@pytest.mark.parametrize(
    ("mode", "expected_protocol"),
    [("auto", "2026-07-28"), ("legacy", "2025-11-25")],
)
def test_uv_run_ynab_mcp_stdio_server_lists_expected_tools(
    mode: str, expected_protocol: str
) -> None:
    """The real stdio subprocess lists all 14 tools on both protocol eras.

    7 read-only + 4 write + 3 analysis tools. Uses a dummy YNAB_PAT: listing tools never calls the YNAB API, so no
    live credentials are needed for this smoke check. YNAB_DEFAULT_BUDGET_ID
    and the AMAZON_* vars are explicitly cleared so a developer's local .env
    (which may set a real default budget or Amazon credentials) can't change
    the expected tool set -- load_dotenv() never overrides an already-set
    environment variable, even an empty one.

    Parametrized over both MCP protocol eras: ``auto`` negotiates the modern
    ``2026-07-28`` revision, ``legacy`` the handshake era that MCP hosts
    without modern support still speak -- the server must serve both.
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

    tool_names, protocol = asyncio.run(_list_tools_and_protocol(transport, mode))

    assert protocol == expected_protocol
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
