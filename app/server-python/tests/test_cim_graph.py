"""The CIM graph app's web API: the layout, the socket that shows the graph, and the commands that
edit it, with the whole server in-process over the three-substation sample grid in an in-process
store. This app is the graph's only writer: an edit is one update, and the state it leads to is
pushed to every open socket. Edits need LazyCIM's CGMES vocabularies (cached, or downloadable) and
are skipped without them."""

from __future__ import annotations

import time

import pytest
from starlette.websockets import WebSocketDisconnect

from pswamp_core.cim import SAMPLE_GRID, CimSettings, open_store, stage

P = "3f5e0000-0000-4000-8000-0000000000"
ALPHA_BETA, ALPHA_GAMMA = P + "24", P + "26"
COUPLER, BAY_BREAKER = P + "34", P + "a1"
SETTINGS = CimSettings(cim_path=SAMPLE_GRID)

needs_profiles = pytest.mark.skipif(not stage(SETTINGS).writable, reason="the CGMES vocabularies are not available to LazyCIM")


def ready(client, timeout: float = 60.0) -> None:
    """Wait for the grid to be loaded (the app loads it in the background when the server starts)."""
    deadline = time.monotonic() + timeout
    while (answer := client.get("/api/cim-graph/layout")).status_code == 503 and "loading" in answer.json()["detail"]:
        assert time.monotonic() < deadline, "the grid never loaded"
        time.sleep(0.05)


@pytest.fixture
def server(monkeypatch):
    """The whole server app, over the sample grid, loaded."""
    monkeypatch.delenv("PSWAMP_TRANSPORT", raising=False)
    monkeypatch.delenv("PSWAMP_CIM_URL", raising=False)
    monkeypatch.setenv("PSWAMP_CIM_PATH", str(SAMPLE_GRID))
    from fastapi.testclient import TestClient

    import server as server_module

    with TestClient(server_module.app) as client:
        ready(client)
        yield client
    open_store(SETTINGS).reset()


def next_state(ws, until=lambda state: True, limit: int = 100) -> dict:
    for _ in range(limit):
        state = ws.receive_json()
        if until(state):
            return state
    raise AssertionError("no such state")


def test_the_layout_is_the_substations_lines_and_breakers_with_their_coordinates(server):
    layout = server.get("/api/cim-graph/layout").json()
    assert sorted(s["name"] for s in layout["substations"]) == ["Alpha", "Beta", "Gamma"]
    assert {b["name"] for b in layout["branches"]} == {
        "Alpha-Beta 400 kV line",
        "Beta-Gamma 400 kV line",
        "Alpha-Gamma 400 kV line",
    }
    assert {b["name"] for b in layout["breakers"]} == {"Beta bus coupler", "Alpha-Gamma bay breaker"}
    # each line already says its one breaker (null: operated through a terminal)
    by_name = {b["name"]: b["breaker"] for b in layout["branches"]}
    assert by_name["Alpha-Gamma 400 kV line"] == BAY_BREAKER and by_name["Alpha-Beta 400 kV line"] is None
    alpha = next(s for s in layout["substations"] if s["name"] == "Alpha")
    assert alpha["position"] == {"lon": 10.0, "lat": 60.0}


def test_the_socket_opens_on_the_state_of_the_graph(server):
    with server.websocket_connect("/api/cim-graph/ws?client_id=201") as ws:
        state = ws.receive_json()
    assert state["type"] == "state" and state["out_of_service"] == []
    assert state["switches"] == {COUPLER: False, BAY_BREAKER: False}


@needs_profiles
def test_opening_a_switch_is_one_update_that_every_socket_sees(server):
    with (
        server.websocket_connect("/api/cim-graph/ws?client_id=202") as one,
        server.websocket_connect("/api/cim-graph/ws?client_id=203") as other,
    ):
        one.receive_json(), other.receive_json()
        ack = server.post(f"/api/cim-graph/switches/{BAY_BREAKER}?client_id=202", json={"open": True}).json()
        assert (ack["status"], ack["applied"]) == ("ok", "open switch")
        for ws in (one, other):  # not just the client that clicked
            state = next_state(ws, lambda s: s["switches"][BAY_BREAKER])
            assert state["out_of_service"] == [ALPHA_GAMMA]
        server.post(f"/api/cim-graph/switches/{BAY_BREAKER}?client_id=202", json={"open": False})
        next_state(one, lambda s: not s["switches"][BAY_BREAKER] and s["out_of_service"] == [])


@needs_profiles
def test_the_edit_is_in_the_store_for_every_reader(server):
    from pswamp_core.cim import connect_reader

    server.post(f"/api/cim-graph/switches/{COUPLER}?client_id=209", json={"open": True})
    assert connect_reader(SETTINGS).from_mRID(COUPLER).open is True


@needs_profiles
def test_a_line_is_taken_out_and_brought_back(server):
    with server.websocket_connect("/api/cim-graph/ws?client_id=204") as ws:
        ws.receive_json()
        ack = server.post(f"/api/cim-graph/lines/{ALPHA_BETA}?client_id=204", json={"open": True}).json()
        assert ack["applied"] == "line out"
        next_state(ws, lambda s: s["out_of_service"] == [ALPHA_BETA])
        server.post(f"/api/cim-graph/lines/{ALPHA_BETA}?client_id=204", json={"open": False})
        next_state(ws, lambda s: s["out_of_service"] == [])


@needs_profiles
def test_a_line_with_a_bay_breaker_is_taken_out_by_it(server):
    with server.websocket_connect("/api/cim-graph/ws?client_id=210") as ws:
        ws.receive_json()
        server.post(f"/api/cim-graph/lines/{ALPHA_GAMMA}?client_id=210", json={"open": True})
        state = next_state(ws, lambda s: s["out_of_service"] == [ALPHA_GAMMA])
        assert state["switches"][BAY_BREAKER] is True


@needs_profiles
def test_what_does_not_apply_is_refused_with_the_reason(server):
    assert server.post("/api/cim-graph/switches/nope?client_id=206", json={"open": True}).status_code == 404
    assert server.post("/api/cim-graph/lines/nope?client_id=206", json={"open": True}).status_code == 404
    already = server.post(f"/api/cim-graph/switches/{COUPLER}?client_id=206", json={"open": False})
    assert already.status_code == 409 and "already closed" in already.json()["detail"]
    in_service = server.post(f"/api/cim-graph/lines/{ALPHA_BETA}?client_id=206", json={"open": False})
    assert in_service.status_code == 409 and "already in service" in in_service.json()["detail"]


@needs_profiles
def test_reset_puts_the_grid_back_as_it_was_loaded(server):
    with server.websocket_connect("/api/cim-graph/ws?client_id=207") as ws:
        ws.receive_json()
        server.post(f"/api/cim-graph/lines/{ALPHA_BETA}?client_id=207", json={"open": True})
        next_state(ws, lambda s: s["out_of_service"] == [ALPHA_BETA])
        assert server.post("/api/cim-graph/reset?client_id=207").json()["applied"] == "reset"
        next_state(ws, lambda s: s["out_of_service"] == [])


def test_a_grid_that_cannot_be_had_is_a_503_with_the_reason_and_the_rest_of_the_server_serves(monkeypatch, tmp_path):
    monkeypatch.delenv("PSWAMP_CIM_URL", raising=False)
    monkeypatch.setenv("PSWAMP_CIM_PATH", str(tmp_path))  # no CGMES files in it
    from fastapi.testclient import TestClient

    import server as server_module

    with TestClient(server_module.app) as server:
        deadline = time.monotonic() + 30
        while (broken := server.get("/api/cim-graph/layout")).json()["detail"] == "the grid is loading":
            assert time.monotonic() < deadline
            time.sleep(0.05)
        assert broken.status_code == 503 and "not available" in broken.json()["detail"]
        with pytest.raises(WebSocketDisconnect) as closed, server.websocket_connect("/api/cim-graph/ws?client_id=208") as ws:
            ws.receive_json()
        assert closed.value.code == 1013
        assert server.get("/healthz").status_code == 200  # the server itself is fine


@needs_profiles
def test_an_edit_reads_nothing_and_writes_one_update(monkeypatch):
    monkeypatch.delenv("PSWAMP_CIM_URL", raising=False)
    from cim_graph.grid import Writer

    writer = Writer(SETTINGS)
    writer.state()  # what the app does once the grid is loaded
    try:
        with writer.repo.measure() as work:
            writer.set_switch(COUPLER, True)
        assert (work.queries, work.write_calls) == (0, 1)
        with writer.repo.measure() as work:
            writer.set_line(ALPHA_GAMMA, True)
        assert work.write_calls == 1
    finally:
        writer.reset()
    assert writer.state().switches[COUPLER] is False  # the writer reads the reset back


def test_a_socket_opened_while_the_grid_loads_gets_the_state_once_it_is_loaded(monkeypatch):
    monkeypatch.delenv("PSWAMP_CIM_URL", raising=False)
    monkeypatch.setenv("PSWAMP_CIM_PATH", str(SAMPLE_GRID))
    from fastapi.testclient import TestClient

    import server as server_module

    with TestClient(server_module.app) as client, client.websocket_connect("/api/cim-graph/ws?client_id=211") as ws:
        assert ws.receive_json()["type"] == "state"  # no 1013 for a grid that is on its way
