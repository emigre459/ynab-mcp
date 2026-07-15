"""YNAB API client construction and budget-id resolution."""

import ynab
from fastmcp.exceptions import ToolError

from ynab_mcp.config import Settings


def build_api_client(settings: Settings) -> ynab.ApiClient:
    """Construct a YNAB ``ApiClient`` from server settings.

    Parameters
    ----------
    settings : Settings
        The server's parsed configuration; only ``ynab_pat`` is used.

    Returns
    -------
    ynab.ApiClient
        A configured API client, reused for the server's process lifetime.
    """
    configuration = ynab.Configuration(access_token=settings.ynab_pat)
    return ynab.ApiClient(configuration)


def resolve_budget_id(budget_id: str | None, settings: Settings) -> str:
    """Resolve an explicit or default YNAB budget id.

    Parameters
    ----------
    budget_id : str | None
        A budget id explicitly supplied by the caller, or ``None`` to fall
        back to the configured default.
    settings : Settings
        The server's parsed configuration, used for its
        ``ynab_default_budget_id`` fallback.

    Returns
    -------
    str
        The budget id to use for the API call.

    Raises
    ------
    ToolError
        If ``budget_id`` is ``None`` and no default budget is configured.
    """
    if budget_id is not None:
        return budget_id
    if settings.ynab_default_budget_id is not None:
        return settings.ynab_default_budget_id
    raise ToolError(
        "No budget_id provided and YNAB_DEFAULT_BUDGET_ID is not configured."
    )


def require_writable(settings: Settings) -> None:
    """Guard a write tool against ``YNAB_READ_ONLY``.

    Parameters
    ----------
    settings : Settings
        The server's parsed configuration.

    Raises
    ------
    ToolError
        If ``settings.ynab_read_only`` is ``True``.
    """
    if settings.ynab_read_only:
        raise ToolError("YNAB_READ_ONLY is enabled; write operations are disabled.")
