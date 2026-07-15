"""Tests for ynab_mcp.errors."""

import ynab
from amazonorders.exception import AmazonOrdersAuthError, AmazonOrdersError
from fastmcp.exceptions import ToolError

from ynab_mcp.errors import translate_api_exception, translate_amazon_exception


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


def test_translate_amazon_exception_auth_error_points_to_login_script() -> None:
    """An auth failure tells the user to re-run the login script."""
    exc = AmazonOrdersAuthError("session expired")

    result = translate_amazon_exception(exc)

    assert isinstance(result, ToolError)
    assert "scripts/amazon_login.py" in str(result)


def test_translate_amazon_exception_generic_error_includes_message() -> None:
    """A non-auth error still surfaces the underlying message."""
    exc = AmazonOrdersError("something broke")

    result = translate_amazon_exception(exc)

    assert isinstance(result, ToolError)
    assert "something broke" in str(result)


def test_translate_api_exception_enriches_429_with_rate_limit_guidance() -> None:
    """A 429 gets rate-limit context and retry-timing guidance appended."""
    exc = ynab.ApiException(
        status=429,
        reason="Too Many Requests",
        body='{"error": {"id": "429", "name": "too_many_requests", '
        '"detail": "Too many requests"}}',
    )

    result = translate_api_exception(exc)

    assert isinstance(result, ToolError)
    assert "Too many requests" in str(result)
    assert "rate limit" in str(result).lower()
    assert "hour" in str(result).lower()


def test_translate_api_exception_does_not_enrich_non_429() -> None:
    """A non-429 ApiException gets only the raw detail, no enrichment appended."""
    exc = ynab.ApiException(
        status=500,
        reason="Internal Server Error",
        body='{"error": {"id": "500", "name": "internal", '
        '"detail": "Service unavailable"}}',
    )

    result = translate_api_exception(exc)

    assert str(result) == "Service unavailable"
