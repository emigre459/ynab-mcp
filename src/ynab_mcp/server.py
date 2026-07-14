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
