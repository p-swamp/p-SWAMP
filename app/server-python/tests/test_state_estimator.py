"""The State Estimator app's web API: the page's socket end to end, with the whole
server in-process. The module itself is tested beside its code, in
``modules/state-estimator/tests/``."""

import pytest


@pytest.fixture
def server(monkeypatch):
    """The whole server, in-memory transport: the module is hosted in-process."""
    monkeypatch.delenv("PSWAMP_TRANSPORT", raising=False)
    from fastapi.testclient import TestClient

    import server as server_module

    with TestClient(server_module.app) as client:
        yield client


def test_the_page_s_socket_serves_the_run(server):
    """The pipeline file's default source (live-synthetic) ties no column to the CIM graph, so the
    estimator has nothing to estimate and publishes nothing: the page gets the run's state, with no
    result. An estimate needs frames that name the graph's Analogs (the live simulation)."""
    with server.websocket_connect("/api/state-estimator/ws?client_id=4242") as ws:
        state = ws.receive_json()
    assert state["type"] == "state"
    assert state["player"] is not None
    assert state["result"] is None
