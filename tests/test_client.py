"""Tests for ynab_mcp.client."""

import pytest
import tenacity
import ynab
from pytest_mock import MockerFixture

from fastmcp.exceptions import ToolError

from ynab_mcp.client import (
    build_api_client,
    call_with_retry,
    require_writable,
    resolve_budget_id,
)
from ynab_mcp.config import Settings


def test_build_api_client_uses_pat_as_access_token() -> None:
    """The configured YNAB_PAT is used as the SDK's access token."""
    settings = Settings(
        ynab_pat="test-token", ynab_default_budget_id=None, ynab_read_only=True
    )

    client = build_api_client(settings)

    assert client.configuration.access_token == "test-token"


def test_resolve_budget_id_prefers_explicit_value() -> None:
    """An explicitly passed budget_id wins over the configured default."""
    settings = Settings(
        ynab_pat="x", ynab_default_budget_id="default-budget", ynab_read_only=True
    )

    assert resolve_budget_id("explicit-budget", settings) == "explicit-budget"


def test_resolve_budget_id_falls_back_to_default() -> None:
    """Omitting budget_id falls back to YNAB_DEFAULT_BUDGET_ID."""
    settings = Settings(
        ynab_pat="x", ynab_default_budget_id="default-budget", ynab_read_only=True
    )

    assert resolve_budget_id(None, settings) == "default-budget"


def test_resolve_budget_id_raises_when_neither_present() -> None:
    """No explicit budget_id and no default configured is an error."""
    settings = Settings(ynab_pat="x", ynab_default_budget_id=None, ynab_read_only=True)

    with pytest.raises(ToolError, match="budget_id"):
        resolve_budget_id(None, settings)


def test_require_writable_raises_when_read_only() -> None:
    """A read-only configuration blocks the call with a clear ToolError."""
    settings = Settings(ynab_pat="x", ynab_default_budget_id=None, ynab_read_only=True)

    with pytest.raises(ToolError, match="YNAB_READ_ONLY"):
        require_writable(settings)


def test_require_writable_passes_when_writable() -> None:
    """A writable configuration does not raise."""
    settings = Settings(ynab_pat="x", ynab_default_budget_id=None, ynab_read_only=False)

    require_writable(settings)


def test_call_with_retry_succeeds_after_transient_429(mocker: MockerFixture) -> None:
    """A 429 followed by success returns the success result."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    func = mocker.Mock(
        side_effect=[
            ynab.ApiException(status=429, reason="Too Many Requests", body=None),
            "ok",
        ]
    )

    result = call_with_retry(func)

    assert result == "ok"
    assert func.call_count == 2


def test_call_with_retry_succeeds_after_transient_5xx(mocker: MockerFixture) -> None:
    """A 5xx followed by success returns the success result (default include_5xx=True)."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    func = mocker.Mock(
        side_effect=[
            ynab.ApiException(status=503, reason="Service Unavailable", body=None),
            "ok",
        ]
    )

    result = call_with_retry(func)

    assert result == "ok"
    assert func.call_count == 2


def test_call_with_retry_include_5xx_false_still_retries_429(
    mocker: MockerFixture,
) -> None:
    """include_5xx=False still retries a 429 -- only 5xx is excluded."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    func = mocker.Mock(
        side_effect=[
            ynab.ApiException(status=429, reason="Too Many Requests", body=None),
            "ok",
        ]
    )

    result = call_with_retry(func, include_5xx=False)

    assert result == "ok"
    assert func.call_count == 2


def test_call_with_retry_include_5xx_false_does_not_retry_5xx(
    mocker: MockerFixture,
) -> None:
    """include_5xx=False fails immediately on a 5xx -- no retry, no duplicate risk."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    exc = ynab.ApiException(status=500, reason="Internal Server Error", body=None)
    func = mocker.Mock(side_effect=[exc, "ok"])

    with pytest.raises(ynab.ApiException) as exc_info:
        call_with_retry(func, include_5xx=False)

    assert exc_info.value.status == 500
    assert func.call_count == 1


def test_call_with_retry_does_not_retry_non_transient_4xx(
    mocker: MockerFixture,
) -> None:
    """A non-429 4xx (e.g. 404) fails on the first attempt, never retried."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    exc = ynab.ApiException(status=404, reason="Not Found", body=None)
    func = mocker.Mock(side_effect=exc)

    with pytest.raises(ynab.ApiException) as exc_info:
        call_with_retry(func)

    assert exc_info.value.status == 404
    assert func.call_count == 1


def test_call_with_retry_exhausts_attempts_and_reraises(
    mocker: MockerFixture,
) -> None:
    """A persistent 429 exhausts _MAX_ATTEMPTS then re-raises the real exception."""
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    exc = ynab.ApiException(status=429, reason="Too Many Requests", body=None)
    func = mocker.Mock(side_effect=exc)

    with pytest.raises(ynab.ApiException) as exc_info:
        call_with_retry(func)

    assert exc_info.value.status == 429
    assert func.call_count == 3
