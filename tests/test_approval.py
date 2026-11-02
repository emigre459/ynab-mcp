"""Tests for ynab_mcp.approval."""

import asyncio
import json
from collections.abc import Callable, Iterator, Mapping
from types import SimpleNamespace
from typing import Any

import mcp_types
import pytest
from conftest import (
    approve_handler,
    cancel_handler,
    decline_handler,
    reject_handler,
)
from fastmcp import Client, Context, FastMCP
from fastmcp.client.elicitation import ElicitResult
from fastmcp.exceptions import ToolError

from ynab_mcp.approval import PendingWrite, fingerprint, require_approval
from ynab_mcp.config import Settings

MODERN = "2026-07-28"
_SETTINGS = Settings(ynab_pat="x", ynab_default_budget_id="b", ynab_read_only=False)


class Harness:
    """A one-tool server whose "write" just records that it happened."""

    def __init__(
        self,
        read_state: Callable[[], Mapping[str, Any]] = dict,
        settings: Settings = _SETTINGS,
    ) -> None:
        self.writes: list[int] = []
        self.prompts: list[str] = []
        self.read_count = 0
        self.mcp = FastMCP("test")

        def counted_read() -> Mapping[str, Any]:
            self.read_count += 1
            return read_state()

        def render(state: Mapping[str, Any]) -> str:
            return f"Apply? state={sorted(state)}"

        @self.mcp.tool(name="w")
        async def tool(x: int, ctx: Context) -> str | mcp_types.InputRequiredResult:
            asked = await require_approval(
                ctx,
                settings,
                tool_name="w",
                budget_id="b",
                arguments={"x": x},
                pending=PendingWrite(read_state=counted_read, render=render),
            )
            if asked is not None:
                return asked
            self.writes.append(x)
            return "written"

    def call(self, mode: str, handler: Any) -> Any:
        """Call the tool once through a real client on the given era."""

        async def _run() -> Any:
            recording = handler
            if handler is not None:

                async def recording(m: str, rt: Any, p: Any, c: Any) -> Any:
                    self.prompts.append(m)
                    return await handler(m, rt, p, c)

            async with Client(
                self.mcp, mode=mode, elicitation_handler=recording
            ) as client:
                return await client.call_tool("w", {"x": 1}, raise_on_error=False)

        return asyncio.run(_run())


def _text(result: Any) -> str:
    return result.content[0].text


def test_approve_proceeds(era_mode: str) -> None:
    """A yes runs the write once, after the human saw the rendered summary."""
    harness = Harness()

    result = harness.call(era_mode, approve_handler)

    assert not result.is_error
    assert harness.writes == [1]
    assert harness.prompts == ["Apply? state=[]"]


@pytest.mark.parametrize(
    ("handler", "expected"),
    [
        (decline_handler, "declined"),
        (cancel_handler, "cancelled"),
        (reject_handler, "declined"),
    ],
)
def test_not_approved_makes_no_write(
    era_mode: str, handler: Any, expected: str
) -> None:
    """Decline, dismiss, and an accepted "no" all refuse without writing."""
    harness = Harness()

    result = harness.call(era_mode, handler)

    assert result.is_error
    assert "Not applied" in _text(result)
    assert expected in _text(result)
    assert harness.writes == []


def test_no_handler_fails_closed(era_mode: str) -> None:
    """A client that can't prompt is refused before any read happens."""
    harness = Harness()

    result = harness.call(era_mode, None)

    assert result.is_error
    assert "YNAB_REQUIRE_WRITE_APPROVAL" in _text(result)
    assert harness.writes == []
    assert harness.read_count == 0


def test_disabled_skips_prompt_and_reads(era_mode: str) -> None:
    """The operator opt-out writes immediately, with no prompt and no reads."""
    harness = Harness(
        settings=Settings(
            ynab_pat="x",
            ynab_default_budget_id="b",
            ynab_read_only=False,
            require_write_approval=False,
        )
    )

    result = harness.call(era_mode, None)

    assert not result.is_error
    assert harness.writes == [1]
    assert harness.read_count == 0


def test_state_change_refuses(era_mode: str) -> None:
    """A value changing between prompt and approval blocks the write."""
    states = iter([{"item a": {"budgeted": 1}}, {"item a": {"budgeted": 2}}])
    harness = Harness(read_state=lambda: next(states))

    result = harness.call(era_mode, approve_handler)

    assert result.is_error
    assert "item a changed" in _text(result)
    assert harness.writes == []


def test_unchanged_state_proceeds(era_mode: str) -> None:
    """The re-check passes when the shown values still hold."""
    harness = Harness(read_state=lambda: {"item a": {"budgeted": 1}})

    result = harness.call(era_mode, approve_handler)

    assert not result.is_error
    assert harness.writes == [1]
    assert harness.read_count == 2


def test_name_only_change_proceeds(era_mode: str) -> None:
    """A rename between prompt and approval doesn't change what the write does."""
    states: Iterator[Mapping[str, Any]] = iter(
        [
            {"item a": {"budgeted": 1, "category_name": "Food"}},
            {"item a": {"budgeted": 1, "category_name": "Groceries"}},
        ]
    )
    harness = Harness(read_state=lambda: next(states))

    result = harness.call(era_mode, approve_handler)

    assert not result.is_error
    assert harness.writes == [1]


def test_recheck_read_failure_refuses(era_mode: str) -> None:
    """A re-check whose read raises fails closed."""
    calls: list[int] = []

    def read() -> Mapping[str, Any]:
        calls.append(1)
        if len(calls) > 1:
            raise RuntimeError("boom")
        return {"item a": {"budgeted": 1}}

    harness = Harness(read_state=read)

    result = harness.call(era_mode, approve_handler)

    assert result.is_error
    assert "couldn't re-check" in _text(result)
    assert harness.writes == []


def test_recheck_none_item_refuses(era_mode: str) -> None:
    """An item that can't be read at re-check time fails closed."""
    states: Iterator[Mapping[str, Any]] = iter(
        [{"item a": {"budgeted": 1}}, {"item a": None}]
    )
    harness = Harness(read_state=lambda: next(states))

    result = harness.call(era_mode, approve_handler)

    assert result.is_error
    assert "item a" in _text(result)
    assert harness.writes == []


def test_render_time_read_failure_still_prompts_then_requires_read(
    era_mode: str,
) -> None:
    """A failed read at prompt time still asks, but the re-check must succeed."""
    calls: list[int] = []

    def read() -> Mapping[str, Any]:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return {"item a": {"budgeted": 1}}

    harness = Harness(read_state=read)

    result = harness.call(era_mode, approve_handler)

    assert harness.prompts == ["Apply? state=[]"]
    assert not result.is_error
    assert harness.writes == [1]


def _approval_round_trip(
    harness: Harness, second_args: dict[str, int], attempts: int
) -> list[Any]:
    """Run round 1, then resend an approved round 2 ``attempts`` times."""

    async def _run() -> list[Any]:
        async with Client(
            harness.mcp, mode="auto", elicitation_handler=approve_handler
        ) as client:
            first = await client.session.call_tool(
                name="w", arguments={"x": 1}, allow_input_required=True
            )
            assert isinstance(first, mcp_types.InputRequiredResult)
            answer = {
                "approve": mcp_types.ElicitResult(
                    action="accept", content={"value": True}
                )
            }
            outcomes = []
            for _ in range(attempts):
                try:
                    outcomes.append(
                        await client.session.call_tool(
                            name="w",
                            arguments=second_args,
                            input_responses=answer,
                            request_state=first.request_state,
                            allow_input_required=True,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    outcomes.append(exc)
            return outcomes

    return asyncio.run(_run())


def test_replay_refused() -> None:
    """Resending an approved round writes once; the replay is not applied."""
    harness = Harness()

    first, replay = _approval_round_trip(harness, {"x": 1}, attempts=2)

    assert not first.is_error
    assert replay.is_error
    assert "already used" in replay.content[0].text
    assert harness.writes == [1]


def test_changed_arguments_refused() -> None:
    """An approval can't be spent on different arguments over the real wire."""
    harness = Harness()

    [outcome] = _approval_round_trip(harness, {"x": 2}, attempts=1)

    assert isinstance(outcome, Exception) or outcome.is_error
    assert harness.writes == []


def _fake_ctx(responses: Any, state: str | None) -> Any:
    """Build a context on a modern connection, past round 1."""
    return SimpleNamespace(
        request_context=SimpleNamespace(protocol_version=MODERN),
        input_responses=responses,
        request_state=state,
    )


def _state(token: str, *, fp: str | None = None) -> str:
    return json.dumps(
        {
            "token": token,
            "fingerprint": fp or fingerprint("w", "b", {"x": 1}),
            "snapshot": {},
        }
    )


def _accepted(content: Any) -> dict[str, mcp_types.ElicitResult]:
    return {"approve": mcp_types.ElicitResult(action="accept", content=content)}


def _gate(ctx: Any) -> None:
    pending = PendingWrite(read_state=dict, render=lambda state: "Apply?")
    asyncio.run(
        require_approval(
            ctx,
            _SETTINGS,
            tool_name="w",
            budget_id="b",
            arguments={"x": 1},
            pending=pending,
        )
    )


def test_fingerprint_mismatch_refused() -> None:
    """Our own argument check holds even if the SDK's binding were absent."""
    ctx = _fake_ctx(_accepted({"value": True}), _state("t-fp", fp="other"))

    with pytest.raises(ToolError, match="arguments changed"):
        _gate(ctx)


@pytest.mark.parametrize("state", [None, "not json", "[]", "{}"])
def test_missing_or_bad_state_refused(state: str | None) -> None:
    """An answer without usable state from round 1 is never approval."""
    ctx = _fake_ctx(_accepted({"value": True}), state)

    with pytest.raises(ToolError, match="arguments changed"):
        _gate(ctx)


@pytest.mark.parametrize(
    "content", [{"value": "true"}, {"value": 1}, {}, None], ids=str
)
def test_loose_accept_refused(content: Any) -> None:
    """Only a literal boolean true counts as yes."""
    ctx = _fake_ctx(_accepted(content), _state(f"t-{content}"))

    with pytest.raises(ToolError, match="declined"):
        _gate(ctx)


def test_missing_approve_key_refused() -> None:
    """A response set without our question's answer is not approval."""
    ctx = _fake_ctx({}, _state("t-missing"))

    with pytest.raises(ToolError, match="Not applied"):
        _gate(ctx)


def test_valid_answer_passes_gate() -> None:
    """The fake-context path does accept a well-formed yes, once."""
    ctx = _fake_ctx(_accepted({"value": True}), _state("t-good"))

    _gate(ctx)

    with pytest.raises(ToolError, match="already used"):
        _gate(ctx)


def _accept_raw(content: Any) -> Any:
    async def handler(m: str, rt: Any, p: Any, c: Any) -> ElicitResult:
        return ElicitResult(action="accept", content=content)

    return handler


@pytest.mark.parametrize(
    "content",
    [{"value": "true"}, {"value": 1}, {"value": "yes"}, {"value": "on"}, {}, None],
    ids=str,
)
def test_loose_accept_refused_over_the_wire(era_mode: str, content: Any) -> None:
    """Only a literal boolean true is approval, on both real eras."""
    harness = Harness()
    handler = _accept_raw(content)

    result = harness.call(era_mode, handler)

    assert result.is_error
    assert "Not applied" in _text(result)
    assert "declined" in _text(result)
    assert harness.writes == []
