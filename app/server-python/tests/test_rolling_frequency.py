"""The Rolling frequency app's web API: the page's socket and its POSTs, with the
whole server in-process. The module itself is tested beside its code, in
``modules/pswamp_modules/rolling_frequency/tests/``."""

from datetime import datetime

import pytest

API = "/api/rolling-frequency"


@pytest.fixture
def server(monkeypatch):
    """The whole server, in-memory transport: the module is hosted in-process."""
    monkeypatch.delenv("PSWAMP_TRANSPORT", raising=False)
    from fastapi.testclient import TestClient

    import server as server_module

    with TestClient(server_module.app) as client:
        yield client


def next_state(ws, until, limit: int = 2000) -> dict:
    for _ in range(limit):
        state = ws.receive_json()
        if until(state):
            return state
    raise AssertionError("no such state")


def instant(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def offset(state: dict) -> float:
    """Seconds from the start of the recording to the cursor."""
    player = state["player"]
    return (instant(player["cursor"]) - instant(player["coverage_start"])).total_seconds()


def at_cursor(state: dict, seconds: float) -> bool:
    """The cursor is ``seconds`` in, and the result showing is for that instant."""
    result = state["result"]
    return offset(state) == seconds and result is not None and result["timestamp"] == state["player"]["cursor"]


def test_the_socket_opens_paused_at_the_start_with_no_result_yet(server):
    with server.websocket_connect(f"{API}/ws?client_id=4201") as ws:
        state = ws.receive_json()
    player = state["player"]
    assert (player["mode"], player["paused"], player["sources"]) == ("replay", True, ["line-trip"])
    assert offset(state) == 0.0
    assert (state["result"], state["from_cache"], state["warm_up_s"]) == (None, False, 5.0)


def test_a_seek_back_shows_the_kept_result_and_so_does_another_client_s(server):
    with server.websocket_connect(f"{API}/ws?client_id=4202") as ws:
        ws.receive_json()
        assert server.post(f"{API}/playback/speed?client_id=4202", json={"speed": 10}).json()["applied"] == "speed"
        server.post(f"{API}/playback/play?client_id=4202")
        played = next_state(ws, lambda s: s["result"] is not None and offset(s) >= 7.0)
        assert not played["from_cache"] and played["result"]["result"]["samples"] == 51
        computed_by = played["result"]["app"]["uuid"]
        server.post(f"{API}/playback/pause?client_id=4202")
        next_state(ws, lambda s: s["player"]["paused"])

        server.post(f"{API}/playback/seek?client_id=4202", json={"offset_s": 6.0})
        back = next_state(ws, lambda s: at_cursor(s, 6.0))
        assert back["from_cache"] and back["result"]["app"]["uuid"] == computed_by
        assert back["player"]["paused"]  # one frame went to the module: it cannot have answered

        server.post(f"{API}/playback/seek?client_id=4202", json={"offset_s": 20.0})  # never played
        ahead = next_state(ws, lambda s: offset(s) == 20.0 and s["result"] is None)
        assert not ahead["from_cache"]

        with server.websocket_connect(f"{API}/ws?client_id=4203") as other:
            assert other.receive_json()["result"] is None
            server.post(f"{API}/playback/seek?client_id=4203", json={"offset_s": 6.0})
            theirs = next_state(other, lambda s: at_cursor(s, 6.0))
            assert theirs["from_cache"] and theirs["result"]["app"]["uuid"] == computed_by


def test_a_command_needs_an_open_page(server):
    assert server.post(f"{API}/playback/play?client_id=4299").status_code == 404
    with server.websocket_connect(f"{API}/ws?client_id=4204") as ws:
        ws.receive_json()
        assert server.post(f"{API}/playback/seek?client_id=4204", json={"offset_s": 99}).status_code == 409
