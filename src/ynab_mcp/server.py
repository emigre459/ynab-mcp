"""FastMCP stdio server exposing read-only YNAB data."""

from fastmcp import FastMCP

from ynab_mcp.amazon_client import (
    build_amazon_orders,
    build_amazon_session,
    build_amazon_transactions,
)
from ynab_mcp.client import build_api_client
from ynab_mcp.config import AmazonSettings, Settings
from ynab_mcp.tools import (
    accounts,
    budgets,
    categories,
    find_amazon_transactions,
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
    ``find-amazon-transactions`` is registered only when Amazon credentials
    (``AMAZON_USERNAME``/``AMAZON_PASSWORD``) are configured.

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

    amazon_settings = AmazonSettings.from_env()
    if amazon_settings is not None:
        amazon_session = build_amazon_session(amazon_settings)
        amazon_orders_client = build_amazon_orders(amazon_session)
        amazon_transactions_client = build_amazon_transactions(amazon_session)
        find_amazon_transactions.register(
            mcp, client, amazon_transactions_client, amazon_orders_client, settings
        )

    return mcp


def main() -> None:
    """Build and run the YNAB MCP server over stdio."""
    build_server().run()


if __name__ == "__main__":
    main()
