"""Integration: call_with_retry against a real HTTP stack (no mocked SDK).

Unit tests elsewhere mock `ynab.AccountsApi` (or similar) directly, so
`call_with_retry`'s tenacity logic runs against a manually-constructed
`ynab.ApiException` -- proving the retry policy is correct, but never
proving the *real* `ynab` SDK actually raises `ApiException` with the
right `.status` from a real HTTP 429/500 response. This test closes that
gap: it points a real `ynab.ApiClient` at a local HTTP server (never the
real YNAB API) that returns 429 then 200, and calls the wrapped
`list_accounts` through the genuine SDK network stack.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Iterator

import pytest
import tenacity
import ynab
from pytest_mock import MockerFixture

from ynab_mcp.tools.accounts import list_accounts


class _FlakyAccountsHandler(BaseHTTPRequestHandler):
    """Returns 429 on the first request, then a valid accounts payload."""

    call_count = 0

    def do_GET(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler's naming
        _FlakyAccountsHandler.call_count += 1
        if _FlakyAccountsHandler.call_count == 1:
            body = json.dumps(
                {
                    "error": {
                        "id": "429",
                        "name": "too_many_requests",
                        "detail": "Too many requests",
                    }
                }
            ).encode()
            self.send_response(429)
        else:
            body = json.dumps(
                {
                    "data": {
                        "accounts": [
                            {
                                "id": "11111111-1111-1111-1111-111111111111",
                                "name": "Checking",
                                "type": "checking",
                                "on_budget": True,
                                "closed": False,
                                "balance": 100000,
                                "cleared_balance": 100000,
                                "uncleared_balance": 0,
                                "transfer_payee_id": "22222222-2222-2222-2222-222222222222",
                                "deleted": False,
                            }
                        ],
                        "server_knowledge": 1,
                    }
                }
            ).encode()
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass  # keep test output quiet


@pytest.fixture
def flaky_server() -> Iterator[str]:
    """Start a local HTTP server that fails once, then succeeds.

    Yields
    ------
    str
        The server's base URL, e.g. ``http://127.0.0.1:54321``.
    """
    _FlakyAccountsHandler.call_count = 0
    server = HTTPServer(("127.0.0.1", 0), _FlakyAccountsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()


@pytest.mark.integration
def test_list_accounts_retries_through_real_sdk_and_http_stack(
    flaky_server: str, mocker: MockerFixture
) -> None:
    """A real 429 HTTP response is retried by the genuine ynab SDK + tenacity.

    No part of the SDK or `ynab.ApiException` is mocked here -- only the
    HTTP server the client talks to is local, standing in for YNAB's API.
    """
    mocker.patch("ynab_mcp.client._wait", tenacity.wait_none())
    configuration = ynab.Configuration(access_token="test-token", host=flaky_server)
    client = ynab.ApiClient(configuration)

    accounts = list_accounts(client, "test-budget")

    assert len(accounts) == 1
    assert accounts[0].name == "Checking"
    assert _FlakyAccountsHandler.call_count == 2
