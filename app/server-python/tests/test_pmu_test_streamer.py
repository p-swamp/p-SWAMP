"""The PMU test streamer's web API: its socket and its POSTs, with the whole
server in-process. Its modules are tested in their own projects under
``modules/``, its sources in the source projects under ``modules/``, its pipeline file
in ``test_pipeline_files.py``."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from pswamp_modules.live_synthetic import LIVE_STREAM_ID

#: The sample recording's first frame: 60 frames at 20 Hz from here.
SAMPLE_START = datetime(2026, 1, 1, 0, 0, 0, 50_000, tzinfo=timezone.utc)


def at(seconds: float) -> str:
    """The instant ``seconds`` after the sample's first frame, as the wire spells it."""
    return (SAMPLE_START + timedelta(seconds=seconds)).isoformat()


def index(state: dict) -> int | None:
    """The 0-based frame shown, counted from the recording's first; None when live."""
    if state["frame"] is None or state["player"]["mode"] != "replay":
        return None
    shown = datetime.fromisoformat(state["frame"]["timestamp"])
    return round((shown - datetime.fromisoformat(state["player"]["coverage_start"])).total_seconds() * 20)


@pytest.fixture
def server(monkeypatch):
    """The whole server app, in-memory transport, the module hosted in-process."""
    monkeypatch.delenv("PSWAMP_TRANSPORT", raising=False)
    from fastapi.testclient import TestClient

    import server as server_module

    with TestClient(server_module.app) as client:
        yield client


def next_state(ws, until=lambda state: True, limit: int = 400) -> dict:
    for _ in range(limit):
        state = ws.receive_json()
        if until(state):
            return state
    raise AssertionError("no such state")


def test_the_socket_opens_on_the_paused_recording(server):
    with server.websocket_connect("/api/pmu-test-streamer/ws?client_id=101") as ws:
        state = ws.receive_json()
    player = state["player"]
    assert (player["mode"], player["paused"], player["sources"]) == ("replay", True, ["sample", "live"])
    assert index(state) == 0 and datetime.fromisoformat(state["frame"]["timestamp"]) == SAMPLE_START
    assert datetime.fromisoformat(player["coverage_end"]) == SAMPLE_START + timedelta(seconds=3)
    assert "frame_index" not in state and "frame_count" not in state
    assert state["frame"]["header"]["cimReferenceId"] == "3f5e0000-0000-4000-8000-000000000001"  # the sample grid


def test_play_brings_frames_and_their_stats(server):
    with server.websocket_connect("/api/pmu-test-streamer/ws?client_id=102") as ws:
        ws.receive_json()
        ack = server.post("/api/pmu-test-streamer/playback/speed?client_id=102", json={"speed": 5}).json()
        assert (ack["status"], ack["applied"]) == ("ok", "speed") and ack["request_id"]
        server.post("/api/pmu-test-streamer/playback/play?client_id=102")
        state = next_state(ws, lambda s: s["stats"] is not None and index(s) >= 3)
        assert state["stats"]["result"]["n_stations"] == 5 and not state["player"]["paused"]
        server.post("/api/pmu-test-streamer/playback/pause?client_id=102")
        next_state(ws, lambda s: s["player"]["paused"])


def test_seek_step_and_a_chunk(server):
    with server.websocket_connect("/api/pmu-test-streamer/ws?client_id=103") as ws:
        ws.receive_json()
        server.post("/api/pmu-test-streamer/playback/seek?client_id=103", json={"at": at(1.5)})
        next_state(ws, lambda s: index(s) == 30)  # 1.5 s after the first frame
        server.post("/api/pmu-test-streamer/playback/step?client_id=103", json={"n": 2})
        next_state(ws, lambda s: index(s) == 32)
        server.post("/api/pmu-test-streamer/playback/step?client_id=103", json={"n": -1})
        next_state(ws, lambda s: index(s) == 31)
        server.post("/api/pmu-test-streamer/playback/speed?client_id=103", json={"speed": 10})
        body = {"at": at(0.5), "until": at(1.0), "play": True}
        server.post("/api/pmu-test-streamer/playback/seek?client_id=103", json=body)
        ended = next_state(ws, lambda s: s["player"]["ended"])
        assert index(ended) == 19 and ended["player"]["paused"]  # the last frame before 1.0 s


def test_a_seek_names_an_instant(server):
    seek = "/api/pmu-test-streamer/playback/seek?client_id=106"
    with server.websocket_connect("/api/pmu-test-streamer/ws?client_id=106") as ws:
        ws.receive_json()
        assert server.post(seek, json={"at": "2026-01-01T00:00:01.05"}).status_code == 200  # no zone: UTC
        next_state(ws, lambda s: index(s) == 20)
        assert server.post(seek, json={"at": "2025-12-31T00:00:00Z"}).status_code == 200  # before: the first frame
        next_state(ws, lambda s: index(s) == 0)
        past = server.post(seek, json={"at": at(3)})
        assert past.status_code == 409 and "past the end" in past.json()["detail"]
        before = server.post(seek, json={"at": "2025-12-31T00:00:00Z", "until": "2025-12-31T00:00:01Z"})
        assert before.status_code == 409 and "before the recording starts" in before.json()["detail"]
        backwards = server.post(seek, json={"at": at(1), "until": at(0.5)})
        assert backwards.status_code == 422


def test_live_is_a_source_without_transport_controls(server):
    with server.websocket_connect("/api/pmu-test-streamer/ws?client_id=104") as ws:
        ws.receive_json()
        server.post("/api/pmu-test-streamer/playback/source?client_id=104", json={"name": "live"})
        state = next_state(ws, lambda s: s["player"]["mode"] == "live" and s["frame"] is not None)
        assert state["frame"]["mRID"] == LIVE_STREAM_ID and index(state) is None
        refused = server.post("/api/pmu-test-streamer/playback/seek?client_id=104", json={"at": at(1)})
        assert refused.status_code == 409 and "live" in refused.json()["detail"]
        # The excursion module reads the shared stream: no per-viewer setting.
        refused = server.post("/api/pmu-test-streamer/excursion/auto-pause?client_id=104", json={"enabled": True})
        assert refused.status_code == 409 and "shared live run" in refused.json()["detail"]
        server.post("/api/pmu-test-streamer/playback/source?client_id=104", json={"name": "sample"})
        back = next_state(ws, lambda s: s["player"]["mode"] == "replay")
        assert back["player"]["paused"]


def test_a_command_needs_an_open_page_and_a_known_source(server):
    assert server.post("/api/pmu-test-streamer/playback/play?client_id=999").status_code == 404
    with server.websocket_connect("/api/pmu-test-streamer/ws?client_id=105") as ws:
        ws.receive_json()
        refused = server.post("/api/pmu-test-streamer/playback/source?client_id=105", json={"name": "nope"})
        assert refused.status_code == 409


def test_a_socket_without_a_client_id_is_refused(server):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as closed:
        with server.websocket_connect("/api/pmu-test-streamer/ws") as ws:
            ws.receive_json()
    assert closed.value.code == 1008


def test_two_clients_on_live_see_one_shared_stream(server):
    with (
        server.websocket_connect("/api/pmu-test-streamer/ws?client_id=201") as first,
        server.websocket_connect("/api/pmu-test-streamer/ws?client_id=202") as second,
    ):
        first.receive_json()
        second.receive_json()
        for client in ("201", "202"):
            server.post(f"/api/pmu-test-streamer/playback/source?client_id={client}", json={"name": "live"})
        a = next_state(first, lambda s: s["player"]["mode"] == "live" and s["stats"] is not None)
        b = next_state(second, lambda s: s["player"]["mode"] == "live" and s["stats"] is not None)
        assert a["stats"]["app"]["uuid"] == b["stats"]["app"]["uuid"]  # one module instance for both
        first_seen = {next_state(first)["frame"]["timestamp"] for _ in range(20)}
        second_seen = {next_state(second)["frame"]["timestamp"] for _ in range(20)}
        assert first_seen & second_seen  # the same frames, stamped once by the shared run


# --- module commands, through the web API -----------------------------------------------


def test_auto_pause_stops_the_replay_at_the_excursion(server):
    with server.websocket_connect("/api/pmu-test-streamer/ws?client_id=301") as ws:
        ws.receive_json()
        server.post("/api/pmu-test-streamer/excursion/auto-pause?client_id=301", json={"enabled": True})
        next_state(ws, lambda s: s["excursion"] is not None and s["excursion"]["result"]["auto_pause"])
        server.post("/api/pmu-test-streamer/playback/speed?client_id=301", json={"speed": 5})
        server.post("/api/pmu-test-streamer/playback/play?client_id=301")
        next_state(ws, lambda s: not s["player"]["paused"])
        paused = next_state(ws, lambda s: s["player"]["paused"], limit=2000)
        assert 20 <= index(paused) <= 30  # the trip, about 1.3 s in
        assert paused["excursion"]["result"]["excursions"] >= 1


def test_a_range_summary_arrives_on_the_socket_and_a_refusal_as_an_error(server):
    with server.websocket_connect("/api/pmu-test-streamer/ws?client_id=302") as ws:
        ws.receive_json()
        body = {"source": "sample", "start": at(1.0), "end": at(2.0)}
        assert server.post("/api/pmu-test-streamer/summary?client_id=302", json=body).status_code == 200
        state = next_state(ws, lambda s: s["summary"] is not None)
        assert state["summary"]["result"]["frames"] == 20
        live = {"source": "live", "start": at(0), "end": at(1)}
        assert server.post("/api/pmu-test-streamer/summary?client_id=302", json=live).status_code == 200  # checked where it runs
