"""The Islanding detection app's web API: the page's socket end to end, with the whole
server in-process. The module itself is tested beside its code, in
``modules/islanding-detection/tests/``."""

import time

import pytest


@pytest.fixture
def server(monkeypatch):
    """The whole server, in-memory transport: the module is hosted in-process."""
    monkeypatch.delenv("PSWAMP_TRANSPORT", raising=False)
    from fastapi.testclient import TestClient

    import server as server_module

    with TestClient(server_module.app) as client:
        yield client


def test_the_page_s_socket_gets_results(server):
    # The module publishes nothing until its 10 s window has filled, and the
    # live feed runs at real time: this test takes that long.
    deadline = time.monotonic() + 30
    with server.websocket_connect("/api/islanding-detection/ws?client_id=4242") as ws:
        while time.monotonic() < deadline:
            state = ws.receive_json()
            if state["result"] is not None:
                break
    assert state["result"]["app"]["name"] == "islanding-detection"
    assert isinstance(state["result"]["result"]["islands"], list)
