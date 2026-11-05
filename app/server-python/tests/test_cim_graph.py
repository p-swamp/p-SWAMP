"""The CIM graph app's web API: the layout, the socket that shows the graph, and the operations, with
the whole server in-process over the three-substation sample grid in an in-process store and the
grid simulation running (ADR-015): an operation is a command to the simulation, which reports what it
did; this app, the graph's only writer, writes that in one update and pushes the state it leads to
to every open socket. Edits need LazyCIM's CGMES vocabularies (cached, or downloadable) and are
skipped without them."""

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


def start(monkeypatch, *, simulated: bool):
    monkeypatch.delenv("PSWAMP_TRANSPORT", raising=False)
    monkeypatch.delenv("PSWAMP_CIM_URL", raising=False)
    monkeypatch.setenv("PSWAMP_CIM_PATH", str(SAMPLE_GRID))
    if simulated:  # the grid simulation is a source of the streamer's pipeline, named rtsim
        monkeypatch.setenv("PMU_TEST_STREAMER_SOURCES", "rtsim:rtsim-from-cim")
    else:
        monkeypatch.setenv("PMU_TEST_STREAMER_SOURCES", "sample:sample-replay")
    from fastapi.testclient import TestClient

    import server as server_module

    return TestClient(server_module.app)


@pytest.fixture
def server(monkeypatch):
    """The whole server app, over the sample grid, loaded, with the grid simulation running."""
    with start(monkeypatch, simulated=True) as client:
        ready(client)
        yield client
    open_store(SETTINGS).reset()


def post(client, path: str, body: dict | None = None, timeout: float = 60.0):
    """POST ``path``, waiting while the simulation is still starting (it answers 409, "not running")."""
    deadline = time.monotonic() + timeout
    while True:
        answer = client.post(path, json=body)
        if not (answer.status_code == 409 and "not running" in answer.json()["detail"]):
            return answer
        assert time.monotonic() < deadline, "the simulation never started"
        time.sleep(0.2)


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
        "Gamma 400/132",
    }
    # a transformer inside one substation is drawn there: that substation at both ends, no route
    (trafo,) = [b for b in layout["branches"] if b["kind"] == "transformer"]
    assert trafo["from_substation"] == trafo["to_substation"] == P + "10" and trafo["path"] == []
    assert {b["name"] for b in layout["breakers"]} == {"Beta bus coupler", "Alpha-Gamma bay breaker"}
    # each line already says its one breaker (null: operated through a terminal)
    by_name = {b["name"]: b["breaker"] for b in layout["branches"]}
    assert by_name["Alpha-Gamma 400 kV line"] == BAY_BREAKER and by_name["Alpha-Beta 400 kV line"] is None
    alpha = next(s for s in layout["substations"] if s["name"] == "Alpha")
    assert alpha["position"] == {"lon": 10.0, "lat": 60.0}
    # what a disturbance can be aimed at: each substation's nodes (a short circuit), the loads (a step)
    gamma = next(s for s in layout["substations"] if s["name"] == "Gamma")
    assert {n["name"]: n["nominal_kv"] for n in gamma["nodes"]} == {"Gamma CN C": 400.0, "Gamma CN C132": 132.0}
    assert {(n["mrid"]) for n in gamma["nodes"]} == {P + "18", P + "19"}
    assert {load["name"]: (load["mrid"], load["substation"], load["p_mw"], load["q_mvar"]) for load in layout["loads"]} == {
        "Beta load LB": (P + "32", P + "09", 400.0, 100.0),
        "Gamma load LC": (P + "33", P + "10", 90.0, 30.0),
    }


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
        ack = post(server, f"/api/cim-graph/switches/{BAY_BREAKER}?client_id=202", {"open": True}).json()
        assert (ack["status"], ack["applied"]) == ("ok", "operate.switch")  # handed to the simulation
        for ws in (one, other):  # not just the client that clicked: what the simulation reported
            state = next_state(ws, lambda s: s["switches"][BAY_BREAKER])
            assert state["out_of_service"] == [ALPHA_GAMMA]
        post(server, f"/api/cim-graph/switches/{BAY_BREAKER}?client_id=202", {"open": False})
        next_state(one, lambda s: not s["switches"][BAY_BREAKER] and s["out_of_service"] == [])


@needs_profiles
def test_the_edit_is_in_the_store_for_every_reader(server):
    from pswamp_core.cim import connect_reader

    with server.websocket_connect("/api/cim-graph/ws?client_id=209") as ws:
        ws.receive_json()
        post(server, f"/api/cim-graph/switches/{COUPLER}?client_id=209", {"open": True})
        next_state(ws, lambda s: s["switches"][COUPLER])
    assert connect_reader(SETTINGS).from_mRID(COUPLER).open is True


@needs_profiles
def test_a_line_is_taken_out_and_brought_back(server):
    with server.websocket_connect("/api/cim-graph/ws?client_id=204") as ws:
        ws.receive_json()
        ack = post(server, f"/api/cim-graph/lines/{ALPHA_BETA}?client_id=204", {"open": True}).json()
        assert ack["applied"] == "operate.line"  # no breaker of its own: by its terminal
        next_state(ws, lambda s: s["out_of_service"] == [ALPHA_BETA])
        post(server, f"/api/cim-graph/lines/{ALPHA_BETA}?client_id=204", {"open": False})
        next_state(ws, lambda s: s["out_of_service"] == [])


@needs_profiles
def test_a_line_with_a_bay_breaker_is_taken_out_by_it(server):
    with server.websocket_connect("/api/cim-graph/ws?client_id=210") as ws:
        ws.receive_json()
        assert post(server, f"/api/cim-graph/lines/{ALPHA_GAMMA}?client_id=210", {"open": True}).json()["applied"] == "operate.switch"
        state = next_state(ws, lambda s: s["out_of_service"] == [ALPHA_GAMMA])
        assert state["switches"][BAY_BREAKER] is True


@needs_profiles
def test_what_does_not_apply_is_refused_with_the_reason(server):
    assert server.post("/api/cim-graph/switches/nope?client_id=206", json={"open": True}).status_code == 404
    assert server.post("/api/cim-graph/lines/nope?client_id=206", json={"open": True}).status_code == 404
    already = post(server, f"/api/cim-graph/switches/{COUPLER}?client_id=206", {"open": False})
    assert already.status_code == 409 and "already closed" in already.json()["detail"]
    in_service = server.post(f"/api/cim-graph/lines/{ALPHA_BETA}?client_id=206", json={"open": False})
    assert in_service.status_code == 409 and "already in service" in in_service.json()["detail"]


@needs_profiles
def test_reset_puts_the_grid_back_as_it_was_loaded(server):
    with server.websocket_connect("/api/cim-graph/ws?client_id=207") as ws:
        ws.receive_json()
        post(server, f"/api/cim-graph/lines/{ALPHA_BETA}?client_id=207", {"open": True})
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
def test_without_the_simulation_the_grid_cannot_be_operated(monkeypatch):
    with start(monkeypatch, simulated=False) as server:
        ready(server)
        refused = server.post(f"/api/cim-graph/switches/{BAY_BREAKER}?client_id=212", json={"open": True})
        assert refused.status_code == 503 and "rtsim" in refused.json()["detail"]
        assert server.post("/api/cim-graph/reset?client_id=212").status_code == 200  # the graph still resets


def test_a_socket_opened_while_the_grid_loads_gets_the_state_once_it_is_loaded(monkeypatch):
    monkeypatch.delenv("PSWAMP_CIM_URL", raising=False)
    monkeypatch.setenv("PSWAMP_CIM_PATH", str(SAMPLE_GRID))
    from fastapi.testclient import TestClient

    import server as server_module

    with TestClient(server_module.app) as client, client.websocket_connect("/api/cim-graph/ws?client_id=211") as ws:
        assert ws.receive_json()["type"] == "state"  # no 1013 for a grid that is on its way
