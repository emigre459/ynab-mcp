"""Tests for ynab_mcp.client."""

import pytest
from fastmcp.exceptions import ToolError

from ynab_mcp.client import build_api_client, resolve_budget_id
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
