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
