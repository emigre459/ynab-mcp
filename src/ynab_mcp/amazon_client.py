"""Amazon session construction and order/transaction client factories."""

from amazonorders.orders import AmazonOrders
from amazonorders.session import AmazonSession
from amazonorders.transactions import AmazonTransactions

from ynab_mcp.config import AmazonSettings


def build_amazon_session(settings: AmazonSettings) -> AmazonSession:
    """Construct an ``AmazonSession`` from Amazon settings.

    Deliberately never calls ``.login()`` -- an MCP stdio tool call has no
    way to handle an interactive CAPTCHA/OTP challenge mid-request. The
    session loads any existing persisted cookies automatically; the first
    login must happen out of band via ``scripts/amazon_login.py``.

    Parameters
    ----------
    settings : AmazonSettings
        The server's parsed Amazon configuration.

    Returns
    -------
    amazonorders.session.AmazonSession
        A session that will reuse a previously persisted login, if any.
    """
    return AmazonSession(
        username=settings.amazon_username,
        password=settings.amazon_password,
        otp_secret_key=settings.amazon_otp_secret_key,
    )


def build_amazon_orders(session: AmazonSession) -> AmazonOrders:
    """Construct an ``AmazonOrders`` client from a session.

    Parameters
    ----------
    session : amazonorders.session.AmazonSession
        A configured Amazon session.

    Returns
    -------
    amazonorders.orders.AmazonOrders
        A client for fetching Amazon order history and detail.
    """
    return AmazonOrders(session)


def build_amazon_transactions(session: AmazonSession) -> AmazonTransactions:
    """Construct an ``AmazonTransactions`` client from a session.

    Parameters
    ----------
    session : amazonorders.session.AmazonSession
        A configured Amazon session.

    Returns
    -------
    amazonorders.transactions.AmazonTransactions
        A client for fetching Amazon per-charge transaction history.
    """
    return AmazonTransactions(session)
