"""Translate YNAB SDK exceptions into FastMCP ToolError instances."""

import json
import logging

from amazonorders.exception import AmazonOrdersAuthError, AmazonOrdersError
import ynab
from fastmcp.exceptions import ToolError

logger = logging.getLogger(__name__)


def translate_api_exception(exc: ynab.ApiException) -> ToolError:
    """Convert a YNAB ``ApiException`` into a FastMCP ``ToolError``.

    Parameters
    ----------
    exc : ynab.ApiException
        The exception raised by a ``ynab`` SDK API call.

    Returns
    -------
    fastmcp.exceptions.ToolError
        A ``ToolError`` carrying the YNAB API's error detail message, ready
        to be raised so the MCP client sees the real failure reason. A 429
        gets additional rate-limit context appended, since YNAB's raw
        detail for a 429 is just the four words "Too many requests" --
        not enough for the calling agent to explain what happened or judge
        whether/when to retry.
    """
    detail = _extract_detail(exc)
    logger.error("YNAB API request failed (status=%s): %s", exc.status, detail)
    if exc.status == 429:
        return ToolError(
            f"{detail} — YNAB rate limit exceeded (this access token allows 200 "
            "requests per rolling hour, and survived automatic retries already). "
            "The API does not report an exact reset time; the quota clears "
            "roughly one hour after the earliest request in the current window. "
            "Wait before retrying, or let the user know to try again in about an hour."
        )
    return ToolError(detail)


def translate_amazon_exception(exc: AmazonOrdersError) -> ToolError:
    """Convert an ``amazon-orders`` exception into a FastMCP ``ToolError``.

    Parameters
    ----------
    exc : amazonorders.exception.AmazonOrdersError
        The exception raised by an ``amazon-orders`` library call.

    Returns
    -------
    fastmcp.exceptions.ToolError
        A ``ToolError`` describing the failure. Authentication failures get
        a remediation hint pointing at ``scripts/amazon_login.py``, since
        that's the only way to re-establish a session -- this tool never
        attempts an interactive login itself.
    """
    if isinstance(exc, AmazonOrdersAuthError):
        logger.error("Amazon session is missing or expired: %s", exc)
        return ToolError(
            "Amazon session is missing or expired. Run "
            "`uv run python scripts/amazon_login.py` to log in again."
        )
    logger.error("Amazon orders request failed: %s", exc)
    return ToolError(f"Amazon orders request failed: {exc}")


def _extract_detail(exc: ynab.ApiException) -> str:
    """Pull the YNAB error ``detail`` field out of an API exception body.

    Parameters
    ----------
    exc : ynab.ApiException
        The exception raised by a ``ynab`` SDK API call.

    Returns
    -------
    str
        The YNAB API's error detail message, or a generic fallback if the
        response body is missing or not in the expected shape.
    """
    if not exc.body:
        return f"YNAB API request failed with status {exc.status}: {exc.reason}"
    try:
        payload = json.loads(exc.body)
        return str(payload["error"]["detail"])
    except (json.JSONDecodeError, KeyError, TypeError):
        return f"YNAB API request failed with status {exc.status}: {exc.body}"
