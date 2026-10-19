"""The live grid feed: every frame of the RT sim reaches the page, read back off the transport, at the
source's rate. The whole server in-process, the in-memory transport, the sample grid (conftest)."""

from __future__ import annotations

import time

import pytest

#: Seconds over which the rate is measured: long enough to see a slow drift, not just a burst.
WINDOW = 20.0


@pytest.fixture
def server(monkeypatch):
    monkeypatch.delenv("PSWAMP_TRANSPORT", raising=False)
    # The streamer's sources are the recording and the synthetic feed; the grid simulation joins by name.
    monkeypatch.setenv("PMU_TEST_STREAMER_SOURCES", "rtsim:rtsim-from-cim")
    monkeypatch.setenv("RTSIM_RATE", "50")
    from fastapi.testclient import TestClient

    import server as server_module

    with TestClient(server_module.app) as client:
        yield client


def test_the_feed_says_its_stations_first(server):
    with server.websocket_connect("/api/cim-live/ws?client_id=601") as ws:
        first = ws.receive_json()
    assert first["type"] == "state" and first["layout"] is not None  # what useServerSocket passes on
    stations = first["layout"]["stations"]
    assert {s["name"] for s in stations} == {"Alpha_400", "Beta_400", "Gamma_132", "Gamma_400"}
    assert all(s["substation"] and s["kv"] for s in stations)  # tied to the CIM graph
    samples = first["samples"]
    assert len(samples["t"]) == len(samples["f_hz"]) and all(len(row) == len(stations) for row in samples["f_hz"])
    assert all(0.95 < v < 1.05 for row in samples["v_pu"] for v in row)


def test_every_frame_reaches_the_page_at_the_source_rate(server):
    with server.websocket_connect("/api/cim-live/ws?client_id=602") as ws:
        ws.receive_json()  # the layout, once the simulation runs
        t: list[float] = []
        pushes, until = 0, time.monotonic() + WINDOW
        while time.monotonic() < until:
            push = ws.receive_json()
            assert push["layout"] is None  # the stations do not change
            t += push["samples"]["t"]
            pushes += 1
    rate = len(t) / WINDOW
    steps = [b - a for a, b in zip(t, t[1:])]
    print(f"\n{rate:.1f} frames/s over {WINDOW:.0f} s, in {pushes} pushes; largest gap {1000 * max(steps):.0f} ms")
    assert rate >= 45  # 50 Hz, every frame
    assert all(step > 0 for step in steps)  # in order, none twice
    assert max(steps) < 0.25  # none lost: a gap is at most the source catching up
