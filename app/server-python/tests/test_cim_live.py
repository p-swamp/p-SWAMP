"""The live grid feed: every frame of the RT sim reaches the page, read back off the transport, at the
source's rate. The whole server in-process, the in-memory transport, the sample grid (conftest)."""

from __future__ import annotations

import time

import pytest

#: Seconds over which the rate is measured: long enough to see a slow drift, not just a burst.
WINDOW = 20.0
#: The simulation's frame period at RTSIM_RATE=50, s.
PERIOD = 0.02


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


def test_the_feed_carries_each_line_end_s_current(server):
    with server.websocket_connect("/api/cim-live/ws?client_id=603") as ws:
        first = ws.receive_json()
    layout, samples = first["layout"], first["samples"]
    ends = layout["line_ends"]
    assert len(ends) == 6 and {(e["end"]) for e in ends} == {1, 2}  # three lines, both ends
    assert all(e["line"] and e["station"] for e in ends)
    assert all(e["limit_a"] is None for e in ends)  # the sample grid has no CurrentLimits
    assert layout["injections"] == []  # the sample grid's PMUs measure no power
    assert all(len(row) == len(ends) and all(a > 0 for a in row) for row in samples["i_a"])  # amperes
    assert all(x is None for row in samples["loading"] for x in row)  # no limit, no loading


def test_the_feed_carries_the_latest_scada_scan_of_the_grid_s_scada_measurements(server):
    with server.websocket_connect("/api/cim-live/ws?client_id=604") as ws:
        first = ws.receive_json()
        points = first["layout"]["scada"]
        scan, until = first["scan"], time.monotonic() + 15
        while scan is None and time.monotonic() < until:
            scan = ws.receive_json()["scan"]  # every 2 s of the simulation's clock
    assert scan is not None and len(scan["values"]) == len(points) == 30  # the sample grid's SCADA
    assert {p["kind"] for p in points} == {"line", "transformer", "generator", "load", "switch", "voltage_level"}
    value = {(p["kind"], p["equipment"], p["quantity"], p["end"]): v for p, v in zip(points, scan["values"], strict=True)}
    assert value[("load", "3f5e0000-0000-4000-8000-000000000032", "P", None)] == pytest.approx(400, rel=0.03)  # Beta load LB
    assert value[("generator", "3f5e0000-0000-4000-8000-000000000030", "P", None)] < 0  # a generator, as CGMES signs it
    assert {v for p, v in zip(points, scan["values"], strict=True) if p["quantity"] == "Pos"} == {1}  # every switch closed
    ends = [p for p in points if p["kind"] == "line" and p["quantity"] == "P"]
    assert len(ends) == 6 and {p["end"] for p in ends} == {1, 2} and all(p["positive_flow_in"] for p in ends)
    assert scan["sim_time"] is not None and scan["t"] > 0


def test_loading_is_the_current_over_its_end_s_limit():
    import numpy as np

    from cim_live.api import _rows

    current = np.array([[300.0, 50.0, 7.0]])  # one frame, three line ends; the second has no limit
    assert _rows(current, np.array([0, 1, 2]), np.array([600.0, np.nan, 7.0]), 4) == [[0.5, None, 1.0]]


def test_every_frame_reaches_the_page_at_the_source_rate(server, caplog):
    with server.websocket_connect("/api/cim-live/ws?client_id=602") as ws:
        ws.receive_json()  # the layout, once the simulation runs
        t: list[float] = []
        lags: list[float] = []
        pushes, until = 0, time.monotonic() + WINDOW
        while time.monotonic() < until:
            push = ws.receive_json()
            assert push["layout"] is None  # the stations do not change
            t += push["samples"]["t"]
            lags.append(push["lag_s"])
            pushes += 1
    rate = len(t) / WINDOW
    periods = [(b - a) / PERIOD for a, b in zip(t, t[1:])]
    missing = sum(round(p) - 1 for p in periods)
    print(f"\n{rate:.1f} frames/s over {WINDOW:.0f} s, in {pushes} pushes; {missing} missing; largest lag {max(lags):.3f} s")
    assert rate >= 45  # 50 Hz
    # Stamped on the schedule: frames are whole periods apart, never closer, so no flat segment, ever.
    assert all(round(p) >= 1 and abs(p - round(p)) < 0.05 for p in periods), periods
    if missing:
        # The engine drops nothing; a frame lost on the way is one the server-side publisher dropped when the
        # loop fell behind (a busy CI runner), and that is said. The page breaks its line there.
        assert any("cannot publish as fast as it produces" in r.getMessage() for r in caplog.records)
    assert all(lag is not None and lag >= 0 for lag in lags)


def test_the_lag_is_how_far_behind_the_server_s_clock_the_newest_frame_is():
    from datetime import datetime, timedelta, timezone

    from cim_live.api import lag_s
    from pswamp_models.pmu import PmuFrame

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def frame(at: datetime) -> PmuFrame:
        return PmuFrame.model_construct(timestamp=at)

    assert lag_s([]) is None
    assert lag_s([frame(now - timedelta(seconds=3)), frame(now - timedelta(seconds=1.25))], now) == 1.25
    assert lag_s([frame(now + timedelta(seconds=0.01))], now) == 0.0  # never ahead: clocks a hair apart
