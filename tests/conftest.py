"""Shared fixtures for exercising write approval on both MCP protocol eras."""

from typing import Any

import pytest
from fastmcp.client.elicitation import ElicitResult


@pytest.fixture(params=["auto", "legacy"])
def era_mode(request: pytest.FixtureRequest) -> str:
    """``fastmcp.Client`` connect mode for each era: modern and handshake."""
    return request.param


async def approve_handler(
    message: str, response_type: Any, params: Any, context: Any
) -> Any:
    """Answer an approval prompt with yes."""
    return response_type(value=True)


async def reject_handler(
    message: str, response_type: Any, params: Any, context: Any
) -> Any:
    """Accept the form but answer the approval question with no."""
    return response_type(value=False)


async def decline_handler(
    message: str, response_type: Any, params: Any, context: Any
) -> ElicitResult:
    """Decline an approval prompt."""
    return ElicitResult(action="decline")


async def cancel_handler(
    message: str, response_type: Any, params: Any, context: Any
) -> ElicitResult:
    """Dismiss an approval prompt."""
    return ElicitResult(action="cancel")
