"""Human approval gate in front of every YNAB write.

The MCP eras ask for input in incompatible ways: on ``2026-07-28`` connections
a tool returns an ``InputRequiredResult`` and is called again with the answer,
and ``ctx.elicit()`` raises; on handshake-era connections the reverse holds. This
module hides that split behind ``require_approval`` and knows nothing about YNAB:
callers describe the write with a ``PendingWrite``.
"""

import hashlib
import json
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import anyio.to_thread
import mcp_types
from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.server.elicitation import (
    AcceptedElicitation,
    CancelledElicitation,
    parse_elicit_response_type,
)
from mcp.shared.exceptions import MCPError
from mcp_types.version import MODERN_PROTOCOL_VERSIONS

from ynab_mcp.config import Settings

ItemState = Mapping[str, object]

_APPROVE_KEY = "approve"
_RESPONSE_TITLE = "Apply these changes?"
# Matches the SDK's default lifetime for sealed request state: an approval
# older than this can no longer be presented, so its token can be forgotten.
_APPROVAL_TTL_SECONDS = 600

_NOTHING_WRITTEN = "No changes were made to YNAB."
_DECLINED = f"Not applied — approval was declined. {_NOTHING_WRITTEN}"
_CANCELLED = f"Not applied — approval was cancelled. {_NOTHING_WRITTEN}"
_CANT_PROMPT = (
    "Not applied — write approval is required but this client can't show "
    f"approval prompts. {_NOTHING_WRITTEN} To allow unattended writes, the "
    "server operator can set YNAB_REQUIRE_WRITE_APPROVAL=false."
)
_ARGUMENTS_CHANGED = (
    f"Not applied — the arguments changed since approval was requested. "
    f"{_NOTHING_WRITTEN}"
)
_REPLAYED = f"Not applied — this approval was already used. {_NOTHING_WRITTEN}"

_used_tokens: dict[str, float] = {}


@dataclass(frozen=True)
class PendingWrite:
    """A write awaiting approval, described by the tool that will perform it.

    Parameters
    ----------
    read_state : Callable[[], Mapping[str, ItemState | None]]
        Reads the current YNAB values the prompt depends on, keyed by a
        human-readable item label. ``None`` marks an item whose read failed.
        May raise if nothing could be read. Empty when there is nothing to
        compare. Called at prompt time and again just before the write.
    render : Callable[[Mapping[str, ItemState | None]], str]
        Builds the prompt text from those values. State keys ending in
        ``_name`` are display-only and ignored by the re-check, since a rename
        doesn't change what the write does.
    """

    read_state: Callable[[], Mapping[str, ItemState | None]]
    render: Callable[[Mapping[str, ItemState | None]], str]


def fingerprint(tool_name: str, budget_id: str, arguments: Mapping[str, object]) -> str:
    """Hash a write's identity so an approval can't be spent on another write.

    Parameters
    ----------
    tool_name : str
        The registered tool name.
    budget_id : str
        The resolved YNAB budget id.
    arguments : Mapping[str, object]
        The write's arguments.

    Returns
    -------
    str
        A SHA-256 hex digest of the canonicalized inputs.
    """
    return _hash({"tool": tool_name, "budget": budget_id, "arguments": arguments})


def _hash(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _digest_state(state: ItemState) -> str:
    return _hash({k: v for k, v in state.items() if not k.endswith("_name")})


def _capture(pending: PendingWrite) -> tuple[str, dict[str, str]]:
    """Read current state and render the prompt; a failed read only degrades it."""
    try:
        states = pending.read_state()
    except Exception:
        states = {}
    snapshot = {
        label: _digest_state(state)
        for label, state in states.items()
        if state is not None
    }
    return pending.render(states), snapshot


def _recheck(pending: PendingWrite, snapshot: Mapping[str, str]) -> None:
    """Refuse unless the values the human saw still hold; failed reads refuse."""
    try:
        current = pending.read_state()
    except Exception as exc:
        raise ToolError(_recheck_failed("current values")) from exc
    for label, state in current.items():
        if state is None:
            raise ToolError(_recheck_failed(label))
    for label, digest in snapshot.items():
        state = current.get(label)
        if state is None:
            raise ToolError(_recheck_failed(label))
        if _digest_state(state) != digest:
            raise ToolError(
                f"Not applied — {label} changed in YNAB since the prompt was "
                f"shown. {_NOTHING_WRITTEN} Re-run to see the current values."
            )


def _recheck_failed(label: str) -> str:
    return (
        f"Not applied — couldn't re-check current values in YNAB ({label}). "
        f"{_NOTHING_WRITTEN}"
    )


def _require_prompt_capable(ctx: Context) -> None:
    capability = mcp_types.ClientCapabilities(
        elicitation=mcp_types.ElicitationCapability()
    )
    if not ctx.session.check_client_capability(capability):
        raise ToolError(_CANT_PROMPT)


def _spend_token(token: str) -> None:
    """Consume a one-time approval token, refusing one already spent."""
    now = time.monotonic()
    for used, spent_at in list(_used_tokens.items()):
        if now - spent_at > _APPROVAL_TTL_SECONDS:
            del _used_tokens[used]
    if token in _used_tokens:
        raise ToolError(_REPLAYED)
    _used_tokens[token] = now


def _parse_round_state(raw: str | None) -> tuple[str, str, dict[str, str]]:
    """Extract (token, fingerprint, snapshot) from round 1's sealed state."""
    try:
        state = json.loads(raw or "")
        token, expected, snapshot = (
            state["token"],
            state["fingerprint"],
            state["snapshot"],
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise ToolError(_ARGUMENTS_CHANGED) from exc
    return token, expected, snapshot


async def _ask_modern_round_one(
    ctx: Context, pending: PendingWrite, write_fingerprint: str
) -> mcp_types.InputRequiredResult:
    _require_prompt_capable(ctx)
    summary, snapshot = await anyio.to_thread.run_sync(_capture, pending)
    schema = parse_elicit_response_type(bool, response_title=_RESPONSE_TITLE).schema
    return mcp_types.InputRequiredResult(
        input_requests={
            _APPROVE_KEY: mcp_types.ElicitRequest(
                params=mcp_types.ElicitRequestFormParams(
                    message=summary, requested_schema=schema
                )
            )
        },
        request_state=json.dumps(
            {
                "token": secrets.token_hex(16),
                "fingerprint": write_fingerprint,
                "snapshot": snapshot,
            }
        ),
    )


async def _settle_modern_round_two(
    ctx: Context, pending: PendingWrite, write_fingerprint: str
) -> None:
    token, expected, snapshot = _parse_round_state(ctx.request_state)
    if expected != write_fingerprint:
        raise ToolError(_ARGUMENTS_CHANGED)
    # Spent before the answer is read, so no replay can ever reach the write.
    _spend_token(token)
    answer = (ctx.input_responses or {}).get(_APPROVE_KEY)
    if isinstance(answer, mcp_types.ElicitResult) and answer.action == "cancel":
        raise ToolError(_CANCELLED)
    if (
        not isinstance(answer, mcp_types.ElicitResult)
        or answer.action != "accept"
        or (answer.content or {}).get("value") is not True
    ):
        raise ToolError(_DECLINED)
    await anyio.to_thread.run_sync(_recheck, pending, snapshot)


async def _ask_handshake(ctx: Context, pending: PendingWrite) -> None:
    _require_prompt_capable(ctx)
    summary, snapshot = await anyio.to_thread.run_sync(_capture, pending)
    try:
        answer = await ctx.elicit(summary, bool, response_title=_RESPONSE_TITLE)
    except MCPError as exc:
        raise ToolError(_CANT_PROMPT) from exc
    if isinstance(answer, CancelledElicitation):
        raise ToolError(_CANCELLED)
    if not isinstance(answer, AcceptedElicitation) or answer.data is not True:
        raise ToolError(_DECLINED)
    await anyio.to_thread.run_sync(_recheck, pending, snapshot)


async def require_approval(
    ctx: Context,
    settings: Settings,
    *,
    tool_name: str,
    budget_id: str,
    arguments: Mapping[str, object],
    pending: PendingWrite,
) -> mcp_types.InputRequiredResult | None:
    """Ask a human to approve a write, refusing unless they explicitly do.

    Parameters
    ----------
    ctx : fastmcp.Context
        The tool call's context.
    settings : Settings
        The server's parsed configuration; ``require_write_approval`` opts out.
    tool_name : str
        The registered tool name, bound into the approval.
    budget_id : str
        The resolved YNAB budget id, bound into the approval.
    arguments : Mapping[str, object]
        The write's arguments, bound into the approval.
    pending : PendingWrite
        How to read current values and render the prompt.

    Returns
    -------
    mcp_types.InputRequiredResult | None
        ``None`` means proceed with the write. A result must be returned from
        the tool as-is: the client will call it again with the answer.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If the write must not happen: declined, cancelled, the client can't
        prompt, a replayed or mismatched approval, or YNAB's values changed.
    """
    if not settings.require_write_approval:
        return None
    request_context = ctx.request_context
    if (
        request_context is None
        or request_context.protocol_version not in MODERN_PROTOCOL_VERSIONS
    ):
        await _ask_handshake(ctx, pending)
        return None
    write_fingerprint = fingerprint(tool_name, budget_id, arguments)
    if ctx.input_responses is None:
        return await _ask_modern_round_one(ctx, pending, write_fingerprint)
    await _settle_modern_round_two(ctx, pending, write_fingerprint)
    return None
