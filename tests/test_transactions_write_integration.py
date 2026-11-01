"""Integration: bulk_manage_transactions' update path through the real SDK.

Unit tests mock `ynab.TransactionsApi` directly, so they can't catch the
SDK itself mis-deserializing a real response. `ynab` 4.2.0 had exactly
that bug: `update_transactions()`'s generated status-code map keyed off
'209' instead of the '200' YNAB returns, so a real successful PATCH came
back as `None` (ynab/ynab-sdk-python#33, fixed in 4.3.0). This test points
a real `ynab.ApiClient` at a local HTTP server (never the real YNAB API)
that answers the PATCH with HTTP 200, pinning that the plain convenience
method returns real transaction data.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Iterator

import pytest
import ynab

from ynab_mcp.tools.transactions_write import bulk_manage_transactions

_TXN_ID = "33333333-3333-3333-3333-333333333333"


class _PatchTransactionsHandler(BaseHTTPRequestHandler):
    """Answers PATCH /plans/{id}/transactions with a 200 SaveTransactionsResponse."""

    requests: list[tuple[str, dict[str, object]]] = []

    def do_PATCH(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler's naming
        length = int(self.headers["Content-Length"])
        payload = json.loads(self.rfile.read(length))
        _PatchTransactionsHandler.requests.append((self.path, payload))
        body = json.dumps(
            {
                "data": {
                    "transaction_ids": [_TXN_ID],
                    "transactions": [
                        {
                            "id": _TXN_ID,
                            "date": "2026-07-14",
                            "amount": -5000,
                            "memo": "updated",
                            "cleared": "uncleared",
                            "approved": True,
                            "deleted": False,
                            "account_id": "11111111-1111-1111-1111-111111111111",
                            "account_name": "Checking",
                            "subtransactions": [],
                        }
                    ],
                    "duplicate_import_ids": [],
                    "server_knowledge": 2,
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
def patch_server() -> Iterator[str]:
    """Start a local HTTP server that accepts transaction PATCHes.

    Yields
    ------
    str
        The server's base URL, e.g. ``http://127.0.0.1:54321``.
    """
    _PatchTransactionsHandler.requests = []
    server = HTTPServer(("127.0.0.1", 0), _PatchTransactionsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()


@pytest.mark.integration
def test_bulk_update_returns_real_transaction_data_on_http_200(
    patch_server: str,
) -> None:
    """A real HTTP 200 PATCH deserializes to real data, not None.

    Nothing in the SDK is mocked -- only the HTTP server it talks to is
    local, standing in for YNAB's API.
    """
    configuration = ynab.Configuration(access_token="test-token", host=patch_server)
    client = ynab.ApiClient(configuration)

    result = bulk_manage_transactions(
        client,
        "test-budget",
        [{"action": "update", "id": _TXN_ID, "memo": "updated"}],
    )

    assert result == [
        {"action": "update", "id": _TXN_ID, "status": "ok", "detail": None}
    ]
    assert len(_PatchTransactionsHandler.requests) == 1
    path, payload = _PatchTransactionsHandler.requests[0]
    assert path == "/plans/test-budget/transactions"
    sent = payload["transactions"]
    assert isinstance(sent, list) and len(sent) == 1
    assert sent[0]["id"] == _TXN_ID
    assert sent[0]["memo"] == "updated"
