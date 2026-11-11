"""The CIM graph app's disturbances (ADR-016): a line trip, a short circuit, a fault cleared by its
protection, a load step. Each is a command to the live simulation only, which the graph never hears
of; what protection does about one (a breaker it opens) is reported, and written. Over the
three-substation sample grid, with the whole server in-process and the simulation running."""

from __future__ import annotations

import time

from test_cim_graph import (  # noqa: F401
    ALPHA_BETA,
    ALPHA_GAMMA,
    BAY_BREAKER,
    P,
    SETTINGS,
    needs_profiles,
    next_state,
    post,
    ready,
    server,
    start,
)

from pswamp_core.cim import connect_reader

GAMMA_400 = P + "18"  # a connectivity node
BETA_LOAD = P + "32"


def api(path: str, client_id: int) -> str:
    return f"/api/cim-graph{path}?client_id={client_id}"


@needs_profiles
def test_a_line_trip_and_its_reconnection_reach_the_simulation_and_never_the_graph(server):  # noqa: F811
    ack = post(server, api(f"/branches/{ALPHA_BETA}/trip", 401)).json()
    assert (ack["status"], ack["applied"]) == ("ok", "trip.branch")
    assert post(server, api(f"/branches/{ALPHA_BETA}/reconnect", 401)).json()["applied"] == "reconnect.branch"
    time.sleep(1)  # anything the simulation said would be written by now
    with server.websocket_connect("/api/cim-graph/ws?client_id=401") as ws:
        assert ws.receive_json()["out_of_service"] == []
    refused = post(server, api("/branches/nowhere/trip", 401))
    assert refused.status_code == 409 and "nowhere" in refused.json()["detail"]


@needs_profiles
def test_what_the_simulation_announces_reaches_every_socket_and_stays_for_the_next(server):  # noqa: F811
    def tripped(state: dict) -> bool:
        return any((e["kind"], e["cause"], e["mRID"]) == ("trip", "disturbance", ALPHA_BETA) for e in state["events"])

    with server.websocket_connect("/api/cim-graph/ws?client_id=406") as ws:
        assert ws.receive_json()["events"] == []
        post(server, api(f"/branches/{ALPHA_BETA}/trip", 406))
        state = next_state(ws, tripped)
        assert state["out_of_service"] == []  # announced, not written
    with server.websocket_connect("/api/cim-graph/ws?client_id=407") as later:
        assert tripped(later.receive_json())  # the recent events are part of the state


@needs_profiles
def test_a_short_circuit_at_a_node_and_its_clearing(server):  # noqa: F811
    ack = post(server, api(f"/nodes/{GAMMA_400}/short-circuit", 402), {"y": 1e3}).json()
    assert ack["applied"] == "short.circuit"
    assert post(server, api(f"/nodes/{GAMMA_400}/clear-short-circuit", 402)).json()["applied"] == "clear.short.circuit"
    assert post(server, api(f"/nodes/{GAMMA_400}/short-circuit", 402), {"y": -1}).status_code == 422


@needs_profiles
def test_a_fault_on_a_line_is_cleared_by_its_breaker_which_the_graph_then_shows_open(server):  # noqa: F811
    with server.websocket_connect("/api/cim-graph/ws?client_id=403") as ws:
        ws.receive_json()
        ack = post(server, api(f"/lines/{ALPHA_GAMMA}/fault", 403), {"end": 1, "clear_ms": 80}).json()
        assert ack["applied"] == "fault.and.clear"
        state = next_state(ws, lambda s: s["switches"][BAY_BREAKER])  # opened by protection, then written
        assert state["out_of_service"] == [ALPHA_GAMMA]
    assert connect_reader(SETTINGS).from_mRID(BAY_BREAKER).open is True


@needs_profiles
def test_a_load_step(server):  # noqa: F811
    ack = post(server, api(f"/loads/{BETA_LOAD}/step", 404), {"p_mw": 450.0}).json()
    assert ack["applied"] == "load.step"
    assert post(server, api(f"/loads/{BETA_LOAD}/step", 404), {}).status_code == 422  # it changes something


@needs_profiles
def test_without_the_simulation_there_is_nothing_to_disturb(monkeypatch):
    with start(monkeypatch, simulated=False) as unsimulated:
        ready(unsimulated)
        refused = unsimulated.post(api(f"/branches/{ALPHA_BETA}/trip", 405))
        assert refused.status_code == 503 and "rtsim" in refused.json()["detail"]
