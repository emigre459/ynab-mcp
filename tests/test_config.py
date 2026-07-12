"""Tests for ynab_mcp.config."""

import pytest

from ynab_mcp.config import Settings


def test_from_env_reads_required_and_optional_vars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All three env vars are read into Settings when present."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("YNAB_PAT", "test-token")
    monkeypatch.setenv("YNAB_DEFAULT_BUDGET_ID", "budget-123")
    monkeypatch.setenv("YNAB_READ_ONLY", "false")

    settings = Settings.from_env()

    assert settings.ynab_pat == "test-token"
    assert settings.ynab_default_budget_id == "budget-123"
    assert settings.ynab_read_only is False


def test_from_env_defaults_when_optional_vars_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing optional vars fall back to None / True."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("YNAB_PAT", "test-token")
    monkeypatch.delenv("YNAB_DEFAULT_BUDGET_ID", raising=False)
    monkeypatch.delenv("YNAB_READ_ONLY", raising=False)

    settings = Settings.from_env()

    assert settings.ynab_default_budget_id is None
    assert settings.ynab_read_only is True


@pytest.mark.parametrize("raw_value", ["false", "0", "no", "FALSE", "No"])
def test_from_env_parses_read_only_false_variants(
    monkeypatch: pytest.MonkeyPatch, raw_value: str
) -> None:
    """Common falsy spellings of YNAB_READ_ONLY parse to False."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("YNAB_PAT", "test-token")
    monkeypatch.setenv("YNAB_READ_ONLY", raw_value)

    settings = Settings.from_env()

    assert settings.ynab_read_only is False


def test_from_env_raises_when_pat_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing YNAB_PAT fails hard with a remediation hint."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("YNAB_PAT", raising=False)

    with pytest.raises(RuntimeError, match="YNAB_PAT"):
        Settings.from_env()


def test_from_env_raises_when_pat_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """A blank YNAB_PAT is treated the same as missing."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("YNAB_PAT", "   ")

    with pytest.raises(RuntimeError, match="YNAB_PAT"):
        Settings.from_env()
