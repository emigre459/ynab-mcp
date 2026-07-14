"""FastMCP stdio server exposing read-only and write YNAB tools."""

import sys

from amazonorders.exception import AmazonOrdersError
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
    budgeted_amount,
    budgets,
    categories,
    find_amazon_transactions,
    lookup,
    months,
    payee_patterns,
    payees,
    payees_write,
    scheduled_transactions,
    spend_analysis,
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
    ``find-amazon-transactions`` is registered only when Amazon credentials
    (``AMAZON_USERNAME``/``AMAZON_PASSWORD``) are configured *and* a session
    can be established: ``AmazonSession.login()`` is called once here, at
    startup -- if a valid session was already persisted by
    ``scripts/amazon_login.py``, this is fast (a single cookie-validity
    check, no interactive challenge); if the session is missing or expired,
    it fails and the tool is skipped for this run rather than registered in
    a broken state.

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
    payee_patterns.register(mcp, client, settings)
    spend_analysis.register(mcp, client, settings)

    amazon_settings = AmazonSettings.from_env()
    if amazon_settings is not None:
        amazon_session = build_amazon_session(amazon_settings)
        try:
            amazon_session.login()
        except AmazonOrdersError as exc:
            print(
                f"Amazon session unavailable, find-amazon-transactions will not be "
                f"registered this run: {exc} Run "
                "`uv run python scripts/amazon_login.py` to re-establish it.",
                file=sys.stderr,
            )
        else:
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
