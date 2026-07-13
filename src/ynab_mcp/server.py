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
