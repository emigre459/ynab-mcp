"""Tests for ynab_mcp.config."""

import pytest

from ynab_mcp.config import AmazonSettings, Settings


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


def test_amazon_settings_from_env_reads_all_vars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All three Amazon env vars are read when present."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("AMAZON_USERNAME", "user@example.com")
    monkeypatch.setenv("AMAZON_PASSWORD", "hunter2")
    monkeypatch.setenv("AMAZON_OTP_SECRET_KEY", "otp-secret")

    settings = AmazonSettings.from_env()

    assert settings is not None
    assert settings.amazon_username == "user@example.com"
    assert settings.amazon_password == "hunter2"
    assert settings.amazon_otp_secret_key == "otp-secret"


def test_amazon_settings_from_env_defaults_otp_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing AMAZON_OTP_SECRET_KEY defaults to None."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("AMAZON_USERNAME", "user@example.com")
    monkeypatch.setenv("AMAZON_PASSWORD", "hunter2")
    monkeypatch.delenv("AMAZON_OTP_SECRET_KEY", raising=False)

    settings = AmazonSettings.from_env()

    assert settings is not None
    assert settings.amazon_otp_secret_key is None


def test_amazon_settings_from_env_returns_none_when_username_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing AMAZON_USERNAME means Amazon integration is unconfigured."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("AMAZON_USERNAME", raising=False)
    monkeypatch.setenv("AMAZON_PASSWORD", "hunter2")

    assert AmazonSettings.from_env() is None


def test_amazon_settings_from_env_returns_none_when_password_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing AMAZON_PASSWORD means Amazon integration is unconfigured."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("AMAZON_USERNAME", "user@example.com")
    monkeypatch.delenv("AMAZON_PASSWORD", raising=False)

    assert AmazonSettings.from_env() is None


def test_amazon_settings_from_env_returns_none_when_both_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No Amazon env vars at all still returns None, not an error."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("AMAZON_USERNAME", raising=False)
    monkeypatch.delenv("AMAZON_PASSWORD", raising=False)

    assert AmazonSettings.from_env() is None
