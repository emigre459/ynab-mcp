"""Translate YNAB SDK exceptions into FastMCP ToolError instances."""

import json
import logging

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
        to be raised so the MCP client sees the real failure reason.
    """
    detail = _extract_detail(exc)
    logger.error("YNAB API request failed (status=%s): %s", exc.status, detail)
    return ToolError(detail)


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
