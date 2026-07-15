"""YNAB API client construction and budget-id resolution."""

from collections.abc import Callable
from typing import TypeVar

import tenacity
import ynab
from fastmcp.exceptions import ToolError

from ynab_mcp.config import Settings

T = TypeVar("T")

_MAX_ATTEMPTS = 3
_BACKOFF_INITIAL_SECONDS = 1
_BACKOFF_MAX_SECONDS = 8

_wait = tenacity.wait_exponential_jitter(
    initial=_BACKOFF_INITIAL_SECONDS, max=_BACKOFF_MAX_SECONDS
)
_stop = tenacity.stop_after_attempt(_MAX_ATTEMPTS)


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


def _is_transient_ynab_error(exc: BaseException, *, include_5xx: bool) -> bool:
    """Determine whether a YNAB ApiException is worth retrying.

    429 is always retryable -- a rate-limit rejection happens at the
    gateway, before any application logic runs, so nothing was written.
    5xx is only retryable when ``include_5xx`` is True -- some call sites
    (non-idempotent creates) pass False since a 5xx there is ambiguous
    about whether the write already landed.

    Parameters
    ----------
    exc : BaseException
        The exception raised by the wrapped call.
    include_5xx : bool
        Whether a 5xx status should also be treated as retryable.

    Returns
    -------
    bool
        Whether ``call_with_retry`` should retry this exception.
    """
    if not isinstance(exc, ynab.ApiException):
        return False
    if exc.status == 429:
        return True
    return include_5xx and exc.status is not None and 500 <= exc.status < 600


def call_with_retry(func: Callable[[], T], *, include_5xx: bool = True) -> T:
    """Call func(), retrying on transient YNAB API failures.

    Always retries on 429. Retries on 5xx too unless ``include_5xx=False``
    (set at call sites where a 5xx response is ambiguous about whether the
    write already landed -- retrying could duplicate it).

    Parameters
    ----------
    func : Callable[[], T]
        A zero-argument callable making one YNAB SDK call.
    include_5xx : bool, optional
        Whether a 5xx status is also retryable, by default ``True``.

    Returns
    -------
    T
        ``func()``'s return value, from whichever attempt succeeded.

    Raises
    ------
    ynab.ApiException
        Non-transient failures propagate on the first attempt. Once
        retries are exhausted, the original exception propagates
        unchanged (``reraise=True``).
    """
    retrying = tenacity.Retrying(
        stop=_stop,
        wait=_wait,
        retry=tenacity.retry_if_exception(
            lambda exc: _is_transient_ynab_error(exc, include_5xx=include_5xx)
        ),
        reraise=True,
    )
    return retrying(func)
