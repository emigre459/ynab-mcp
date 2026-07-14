"""One-time interactive Amazon login.

Run this manually (and again whenever the session expires) so the
find-amazon-transactions tool can reuse a persisted session without ever
attempting an interactive login itself:

    uv run playwright install chromium   # one-time per machine
    uv run python scripts/amazon_login.py

Amazon commonly answers a login attempt with a JavaScript-based
bot-detection or "ACIC" challenge; the `playwright install chromium` step
provisions the headless browser build_amazon_session() uses to solve it
automatically.
"""

import sys

from ynab_mcp.amazon_client import build_amazon_session
from ynab_mcp.config import AmazonSettings


def main() -> None:
    """Log into Amazon interactively and persist the session to disk."""
    settings = AmazonSettings.from_env()
    if settings is None:
        print(
            "AMAZON_USERNAME and AMAZON_PASSWORD must be set in .env before "
            "logging in.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    session = build_amazon_session(settings)
    session.login()
    print("Amazon login succeeded; session persisted for the MCP server to reuse.")


if __name__ == "__main__":
    main()
