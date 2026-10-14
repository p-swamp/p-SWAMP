"""A socket the server cannot serve is accepted, then closed with 1008.

A close code only reaches a browser on an accepted socket: a refused handshake
reads as 1006 there, which the web client retries for ever. So entering
``websocket_connect`` is half of every check below: it raises if the handshake
was refused."""

from __future__ import annotations

import pytest
from starlette.websockets import WebSocketDisconnect


@pytest.fixture
def server(monkeypatch):
    """The whole server app, in-memory transport."""
    monkeypatch.delenv("PSWAMP_TRANSPORT", raising=False)
    from fastapi.testclient import TestClient

    import server as server_module

    with TestClient(server_module.app) as client:
        yield client


def closed_with(server, path: str) -> int:
    """The code an accepted socket on ``path`` is closed with."""
    with server.websocket_connect(path) as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    return closed.value.code


def test_a_socket_on_a_path_no_app_serves_is_accepted_then_closed(server):
    assert closed_with(server, "/api/no-such-app/ws?client_id=1") == 1008


@pytest.mark.parametrize("app", ["reference-subapp", "errors", "pmu-test-streamer", "app-status"])
def test_a_socket_without_a_usable_client_id_is_accepted_then_closed(server, app):
    assert closed_with(server, f"/api/{app}/ws") == 1008
    assert closed_with(server, f"/api/{app}/ws?client_id=abc") == 1008


def test_an_unknown_api_path_is_still_a_404(server):
    assert server.get("/api/no-such-app").status_code == 404
