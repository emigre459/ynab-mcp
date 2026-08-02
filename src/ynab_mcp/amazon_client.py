"""Amazon session construction and order/transaction client factories."""

from amazonorders.conf import AmazonOrdersConfig
from amazonorders.exception import AmazonOrdersError
from amazonorders.orders import AmazonOrders
from amazonorders.session import AmazonSession
from amazonorders.transactions import AmazonTransactions

from ynab_mcp.config import AmazonSettings
from ynab_mcp.errors import translate_amazon_exception

# Amazon commonly answers a login attempt with a JavaScript-based
# bot-detection or "ACIC" challenge. The library's default auth-form chain
# only *blocks* on these (raising AmazonOrdersAuthError with a remediation
# hint) unless these Playwright-backed solvers are explicitly registered --
# requires the `amazon-orders[browser]` extra and `playwright install
# chromium`, both declared as hard requirements in pyproject.toml.
_BROWSER_AUTH_FORMS_CLASSES = [
    "amazonorders.contrib.browser.playwright.PlaywrightAcicForm",
    "amazonorders.contrib.browser.playwright.PlaywrightJSAuthForm",
]


def build_amazon_session(settings: AmazonSettings) -> AmazonSession:
    """Construct an ``AmazonSession`` from Amazon settings.

    This function itself never calls ``.login()`` -- the caller (``server.py``)
    does that exactly once, right after construction, at server startup.
    That single call is what actually flips ``AmazonSession.is_authenticated``
    to ``True``; the ``amazon-orders`` library requires this even when a
    valid session was already persisted to disk (loading cookies at
    construction time is not, by itself, enough for ``AmazonOrders``/
    ``AmazonTransactions`` calls to proceed). Calling ``.login()`` is safe at
    startup because it fast-paths (a single request, no interactive
    challenge) when the persisted cookies are still valid; a genuinely
    missing/expired session must be re-established out of band via
    ``scripts/amazon_login.py``, which can drive a real (headless) browser
    through any JavaScript-based challenge Amazon presents -- something no
    MCP stdio tool call could do mid-request.

    Parameters
    ----------
    settings : AmazonSettings
        The server's parsed Amazon configuration.

    Returns
    -------
    amazonorders.session.AmazonSession
        A session ready for the caller to call ``.login()`` on.
    """
    config = AmazonOrdersConfig(
        data={
            "auth_forms_classes": _BROWSER_AUTH_FORMS_CLASSES,
            # The library's 30s default is often too short for a real
            # challenge round-trip against Amazon's bot-detection.
            "browser_timeout": 90,
        }
    )
    return AmazonSession(
        username=settings.amazon_username,
        password=settings.amazon_password,
        otp_secret_key=settings.amazon_otp_secret_key,
        config=config,
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


def build_worker_amazon_orders(settings: AmazonSettings) -> AmazonOrders:
    """Construct a fresh, independently-authenticated ``AmazonOrders`` client.

    Unlike ``build_amazon_session``/``build_amazon_orders`` (used once at
    server startup for the primary, long-lived session), this builds a
    brand-new ``AmazonSession`` on every call and logs it in immediately.
    It exists for ``find_amazon_transactions``' concurrent enrichment
    fetches, where each worker thread needs its own independent
    ``requests.Session`` to avoid any risk of concurrent cookie-jar access
    on a session shared across threads. The login call fast-paths (a
    single cheap request, no interactive challenge) as long as valid
    persisted cookies already exist from the server's own startup login.

    Parameters
    ----------
    settings : AmazonSettings
        The server's parsed Amazon configuration.

    Returns
    -------
    amazonorders.orders.AmazonOrders
        A client backed by a freshly-authenticated, independent session.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If the login attempt fails (e.g. the persisted session has
        actually expired and a real interactive challenge would be
        required, which cannot complete inside a worker thread).
    """
    session = build_amazon_session(settings)
    try:
        session.login()
    except AmazonOrdersError as exc:
        raise translate_amazon_exception(exc) from exc
    return build_amazon_orders(session)
