"""Tests for ynab_mcp.amazon_client."""

from pytest_mock import MockerFixture

from ynab_mcp.amazon_client import (
    build_amazon_orders,
    build_amazon_session,
    build_amazon_transactions,
)
from ynab_mcp.config import AmazonSettings


def _settings() -> AmazonSettings:
    return AmazonSettings(
        amazon_username="user@example.com",
        amazon_password="hunter2",
        amazon_otp_secret_key="otp-secret",
    )


def test_build_amazon_session_passes_credentials_and_never_logs_in(
    mocker: MockerFixture,
) -> None:
    """The session is built from settings; .login() is never called here."""
    session_cls = mocker.patch("ynab_mcp.amazon_client.AmazonSession")

    session = build_amazon_session(_settings())

    session_cls.assert_called_once_with(
        username="user@example.com",
        password="hunter2",
        otp_secret_key="otp-secret",
    )
    assert session is session_cls.return_value
    session_cls.return_value.login.assert_not_called()


def test_build_amazon_orders_wraps_session(mocker: MockerFixture) -> None:
    """AmazonOrders is constructed from the given session."""
    orders_cls = mocker.patch("ynab_mcp.amazon_client.AmazonOrders")
    session = mocker.Mock()

    orders = build_amazon_orders(session)

    orders_cls.assert_called_once_with(session)
    assert orders is orders_cls.return_value


def test_build_amazon_transactions_wraps_session(mocker: MockerFixture) -> None:
    """AmazonTransactions is constructed from the given session."""
    transactions_cls = mocker.patch("ynab_mcp.amazon_client.AmazonTransactions")
    session = mocker.Mock()

    transactions = build_amazon_transactions(session)

    transactions_cls.assert_called_once_with(session)
    assert transactions is transactions_cls.return_value
