"""Tests for ynab_mcp.errors."""

import ynab
from fastmcp.exceptions import ToolError

from ynab_mcp.errors import translate_api_exception


def test_translate_api_exception_extracts_detail_from_body() -> None:
    """The YNAB error detail is pulled out of the JSON response body."""
    exc = ynab.ApiException(
        status=404,
        reason="Not Found",
        body='{"error": {"id": "404", "name": "not_found", '
        '"detail": "Budget not found"}}',
    )

    result = translate_api_exception(exc)

    assert isinstance(result, ToolError)
    assert "Budget not found" in str(result)


def test_translate_api_exception_falls_back_when_body_missing() -> None:
    """A missing body still produces a useful, non-empty message."""
    exc = ynab.ApiException(status=500, reason="Internal Server Error", body=None)

    result = translate_api_exception(exc)

    assert "500" in str(result)
    assert "Internal Server Error" in str(result)


def test_translate_api_exception_falls_back_when_body_malformed() -> None:
    """A body that isn't the expected error JSON shape doesn't crash."""
    exc = ynab.ApiException(status=502, reason="Bad Gateway", body="not json")

    result = translate_api_exception(exc)

    assert "502" in str(result)
