"""Server configuration read from the environment."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

_FALSY_VALUES = {"false", "0", "no"}


@dataclass(frozen=True)
class Settings:
    """Runtime configuration for the YNAB MCP server.

    Parameters
    ----------
    ynab_pat : str
        The YNAB personal access token used to authenticate API calls.
    ynab_default_budget_id : str | None
        A budget id every tool falls back to when the caller omits one.
    ynab_read_only : bool
        Whether write/mutation tools are permitted. Currently read but
        unenforced -- no write tools exist yet.
    """

    ynab_pat: str
    ynab_default_budget_id: str | None
    ynab_read_only: bool

    @classmethod
    def from_env(cls) -> "Settings":
        """Build ``Settings`` from the process environment.

        Loads `.env` first, then reads ``YNAB_PAT``,
        ``YNAB_DEFAULT_BUDGET_ID``, and ``YNAB_READ_ONLY``.

        Returns
        -------
        Settings
            The parsed server configuration.

        Raises
        ------
        RuntimeError
            If ``YNAB_PAT`` is missing or empty.
        """
        load_dotenv()

        ynab_pat = os.environ.get("YNAB_PAT", "").strip()
        if not ynab_pat:
            raise RuntimeError(
                "YNAB_PAT is not set. Copy .env.example to .env and set "
                "YNAB_PAT to a YNAB personal access token "
                "(https://api.ynab.com/#personal-access-tokens)."
            )

        default_budget_id = os.environ.get("YNAB_DEFAULT_BUDGET_ID", "").strip() or None

        read_only_raw = os.environ.get("YNAB_READ_ONLY", "true").strip().lower()
        ynab_read_only = read_only_raw not in _FALSY_VALUES

        return cls(
            ynab_pat=ynab_pat,
            ynab_default_budget_id=default_budget_id,
            ynab_read_only=ynab_read_only,
        )


@dataclass(frozen=True)
class AmazonSettings:
    """Amazon credentials for the find-amazon-transactions tool.

    Parameters
    ----------
    amazon_username : str
        The Amazon account email/username used to authenticate.
    amazon_password : str
        The Amazon account password used to authenticate.
    amazon_otp_secret_key : str | None
        The TOTP secret key for automatic OTP-based 2FA solving, if the
        account has 2FA enabled.
    """

    amazon_username: str
    amazon_password: str
    amazon_otp_secret_key: str | None

    @classmethod
    def from_env(cls) -> "AmazonSettings | None":
        """Build ``AmazonSettings`` from the process environment.

        Loads `.env` first (safe to call even if ``Settings.from_env()``
        already did, so this also works when called standalone from
        ``scripts/amazon_login.py``), then reads ``AMAZON_USERNAME``,
        ``AMAZON_PASSWORD``, and ``AMAZON_OTP_SECRET_KEY``.

        Returns
        -------
        AmazonSettings | None
            The parsed Amazon configuration, or ``None`` if
            ``AMAZON_USERNAME`` or ``AMAZON_PASSWORD`` is unset. Unlike
            ``Settings.from_env``, this does not raise -- Amazon
            integration is optional server-wide functionality.
        """
        load_dotenv()

        username = os.environ.get("AMAZON_USERNAME", "").strip()
        password = os.environ.get("AMAZON_PASSWORD", "").strip()
        if not username or not password:
            return None

        otp_secret_key = os.environ.get("AMAZON_OTP_SECRET_KEY", "").strip() or None

        return cls(
            amazon_username=username,
            amazon_password=password,
            amazon_otp_secret_key=otp_secret_key,
        )
