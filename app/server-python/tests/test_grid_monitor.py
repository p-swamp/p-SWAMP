"""The grid monitor's backend: the grid it draws (read from the CIM graph), the follower of the live
grid that every panel reads, and the panels' sockets end to end with the whole server in-process,
over the three-substation sample grid (conftest). The modules are tested beside their code."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from pswamp_core.cim import SAMPLE_GRID, CimSettings, open_store, stage
from pswamp_models.common import AlarmEvent, AppIdentity
from pswamp_models.islanding_detection import IslandingDetectionBody, IslandingDetectionResult
from pswamp_models.line_outage import LineOutageBody, LineOutageChange, LineOutageResult, MeasuredCurrent
from pswamp_models.pmu import PmuFrame, PmuHeader

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
SETTINGS = CimSettings(cim_path=SAMPLE_GRID)
STATIONS = {"Alpha_400", "Beta_400", "Gamma_400", "Gamma_132"}
BRANCHES = {"Alpha-Beta_400_kV_line", "Alpha-Gamma_400_kV_line", "Beta-Gamma_400_kV_line", "Gamma_400/132"}

needs_profiles = pytest.mark.skipif(not stage(SETTINGS).writable, reason="the CGMES vocabularies are not available to LazyCIM")


# --- the grid ---------------------------------------------------------------


def test_the_grid_is_a_bus_per_voltage_level_and_its_branches():
    from grid_monitor.topology import read_topology

    topology = read_topology()
    model = topology.model
    assert {bus.name for bus in model.buses} == STATIONS  # the live stream's station names
    assert {bus.name: bus.v_nom for bus in model.buses}["Gamma_132"] == 132
    assert {branch.name for branch in model.branches} == BRANCHES
    assert {branch.name: branch.kind for branch in model.branches}["Gamma_400/132"] == "trafo"
    diagram = model.diagram
    assert set(diagram.buses) == STATIONS and set(diagram.branches) == BRANCHES
    for branch in model.branches:  # every route runs from its from-bus to its to-bus
        path = diagram.branches[branch.name]
        assert tuple(path[0]) == tuple(diagram.buses[branch.from_bus])
        assert tuple(path[-1]) == tuple(diagram.buses[branch.to_bus])
    # Two voltage levels of one substation are drawn apart, but close.
    gamma400, gamma132 = np.array(diagram.buses["Gamma_400"]), np.array(diagram.buses["Gamma_132"])
    assert 0 < np.linalg.norm(gamma400 - gamma132) < 0.1
    # The sample grid is in southern Norway, inside the Nordic outlines.
    assert diagram.countries and diagram.outlines
    # Every line end's current (two per line, three lines; a magnitude and an angle each) finds its branch.
    assert sorted(topology.branch_of_analog.values()) == sorted(4 * sorted(BRANCHES - {"Gamma_400/132"}))


# --- the follower -----------------------------------------------------------


def header(stations: list[str]) -> PmuHeader:
    return PmuHeader(
        station=stations, channel=["f"] * len(stations), measurement=["f"] * len(stations),
        units=["Hz"] * len(stations), data_rate=50.0,
    )  # fmt: skip


def fill(grid, frequencies: list[float | None], seconds: float = 2.0) -> None:
    h = header([f"s{i}" for i in range(len(frequencies))])
    for k in range(int(seconds * 50)):
        grid.window.append(PmuFrame(mRID="t", timestamp=T0 + timedelta(seconds=k / 50), header=h, values=frequencies))


APP = AppIdentity(name="islanding-detection", uuid="app-1")
OUTAGE_APP = AppIdentity(name="line-outage", uuid="app-2")


def islanding(islands: list[list[str]]) -> IslandingDetectionResult:
    return IslandingDetectionResult(
        timestamp=T0,
        app=APP,
        parameters={"window_length_s": 10.0, "mean_threshold": 0.05, "eval_freq": 1.0},
        result=IslandingDetectionBody(islands=islands, status="Emergency" if islands else "OK"),
    )


def outage(changes: list[tuple[str, list[str]]], disconnected: list[str]) -> LineOutageResult:
    current = lambda channel: MeasuredCurrent(station="s0", channel=channel)  # noqa: E731
    return LineOutageResult(
        timestamp=T0,
        app=OUTAGE_APP,
        parameters={"window_s": 0.2},
        result=LineOutageBody(
            changes=[LineOutageChange(kind=kind, currents=[current(c) for c in channels]) for kind, channels in changes],
            disconnected=[current(c) for c in disconnected],
            status="Alert" if disconnected else "OK",
        ),
    )


def test_the_main_system_is_every_station_with_a_frequency_in_no_island():
    from grid_monitor.live import LiveGrid

    grid = LiveGrid()
    fill(grid, [50.0, 50.0, 50.2, None])  # s3 has no frequency: it is in no group
    grid.handle(islanding([["s2"]]))
    islands = grid.islanding.islands
    assert [(i.index, i.stations) for i in islands] == [(0, ["s0", "s1"]), (1, ["s2"])]
    assert islands[0].mean_freq == pytest.approx(50.0) and islands[1].mean_freq == pytest.approx(50.2)
    assert grid.island_of == {"s0": 0, "s1": 0, "s2": 1}
    assert grid.islanding.status == "Emergency" and grid.islanding.parameters.window_length == 10.0
    assert [(s.app_name, s.status) for s in grid.statuses()] == [("islanding-detection", "Emergency")]


def test_the_outage_log_is_newest_first_and_says_what_is_out_now():
    from grid_monitor.live import LiveGrid

    grid = LiveGrid()
    grid.handle(outage([], []))
    assert grid.outages.events == [] and grid.outages.disconnected == []
    grid.handle(outage([("disconnect", ["I_L1", "I_L2"])], ["I_L1", "I_L2"]))
    grid.handle(outage([("connect", ["I_L2"])], ["I_L1"]))
    log = grid.outages
    assert [(e.kind, e.branches) for e in log.events] == [("connect", ["L2"]), ("disconnect", ["L1", "L2"])]
    assert log.disconnected == ["L1"]  # named by the channel, with no topology to name it
    assert log.app_name == "line-outage" and log.window_length == 0.2


def test_a_current_s_branch_is_found_through_its_analog():
    from grid_monitor.live import LiveGrid
    from grid_monitor.topology import Topology
    from pswamp_web.wire import GridModel

    grid = LiveGrid()
    grid.topology = Topology(model=GridModel(buses=[], branches=[], pmus=[], bbox=(0, 0, 1, 1)), branch_of_analog={"a1": "Line_one"})
    assert grid.branch_of(MeasuredCurrent(station="s", channel="I_Line one", analog="a1")) == "Line_one"
    assert grid.branch_of(MeasuredCurrent(station="s", channel="I_other", analog="unknown")) == "other"


async def test_a_view_wakes_on_what_it_listens_for_and_on_every_nudge():
    from grid_monitor.live import ALARMS, LINE_OUTAGE, LiveGrid

    grid = LiveGrid()
    with grid.updates(ALARMS) as alarms, grid.updates(LINE_OUTAGE) as outages:
        grid.handle(
            AlarmEvent(timestamp=T0, alarm_uuid="al-1", app=APP, type="init", status="Emergency", message="an island")
        )
        assert (await asyncio.wait_for(alarms.get(), 1)).topic == ALARMS
        assert outages.empty()
        assert [a.status for a in grid.alarms.list()] == ["unseen"]
        grid.nudge()
        assert (await asyncio.wait_for(outages.get(), 1)).topic is None


# --- the panels, end to end --------------------------------------------------


@pytest.fixture
def server(monkeypatch):
    """The whole server, in-memory transport: the grid-monitor pipeline's modules are hosted in-process."""
    monkeypatch.delenv("PSWAMP_TRANSPORT", raising=False)
    monkeypatch.delenv("PSWAMP_CIM_URL", raising=False)
    monkeypatch.delenv("GRID_MONITOR_SOURCES", raising=False)
    from fastapi.testclient import TestClient

    import server as server_module

    with TestClient(server_module.app) as client:
        yield client
    open_store(SETTINGS).reset()


def receive_until(ws, until, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        message = ws.receive_json()
        if until(message):
            return message
    raise AssertionError("no such message in time")


def test_every_panel_shows_the_live_grid(server):
    model = server.get("/api/grid/model").json()
    assert {bus["name"] for bus in model["buses"]} == STATIONS
    catalogue = server.get("/api/time-window/channels").json()["channels"]
    assert {c["station"] for c in catalogue if c["measurement"] == "f"} == STATIONS

    with server.websocket_connect("/api/time-window/ws?client_id=5101") as ws:
        first = ws.receive_json()
        assert first["mode"] == "full" and {c["measurement"] for c in first["channels"]} == {"f"}
        assert first["sampling_rate"] == 50
        assert receive_until(ws, lambda m: m["mode"] == "append")["t"]

    with server.websocket_connect("/api/phasors/ws?client_id=5101") as ws:
        phasors = receive_until(ws, lambda m: all(p["mag"] is not None for p in m["phasors"]))["phasors"]
    by_station = {p["station"]: p for p in phasors}
    assert set(by_station) == STATIONS
    assert 0.95 * 400e3 < by_station["Alpha_400"]["mag"] < 1.05 * 400e3  # volts, from the stream's kV
    assert all(abs(p["ang"]) < np.pi for p in phasors)  # radians, from the stream's degrees

    # The detector publishes nothing until its 10 s window has filled: this takes that long.
    with server.websocket_connect("/api/islanding/ws?client_id=5101") as ws:
        state = receive_until(ws, lambda m: m["islanding"] is not None)
    main = state["islanding"]["islands"][0]
    assert main["index"] == 0 and set(main["stations"]) == STATIONS and 49.5 < main["mean_freq"] < 50.5

    with server.websocket_connect("/api/app-status/ws?client_id=5101") as ws:
        table = receive_until(ws, lambda m: len(m["apps"]) == 2)
    assert {a["app_name"] for a in table["apps"]} == {"islanding-detection", "line-outage"}
    assert table["feed"]["source"] == "rtsim" and table["feed"]["streaming"] and table["feed"]["data_rate"] == 50


@needs_profiles
def test_a_line_taken_out_on_the_graph_is_an_outage_on_its_branch(server):
    deadline = time.monotonic() + 60
    while (answer := server.get("/api/cim-graph/layout")).status_code == 503:  # the grid is loading
        assert time.monotonic() < deadline, "the grid never loaded"
        time.sleep(0.05)
    layout = answer.json()
    line = next(b for b in layout["branches"] if b["name"] == "Beta-Gamma 400 kV line")
    path, body = f"/api/cim-graph/lines/{line['mrid']}?client_id=5102", {"open": True}
    while (answer := server.post(path, json=body)).status_code == 409 and "not running" in answer.json()["detail"]:
        assert time.monotonic() < deadline, "the simulation never started"  # it operates the line (ADR-015)
        time.sleep(0.2)
    assert answer.status_code == 200
    with server.websocket_connect("/api/line-outage/ws?client_id=5102") as ws:
        log = receive_until(ws, lambda m: m["disconnected"])
    assert log["disconnected"] == ["Beta-Gamma_400_kV_line"]  # a GridBranch.name of /api/grid/model
    assert log["events"][0]["kind"] == "disconnect" and log["events"][0]["branches"] == ["Beta-Gamma_400_kV_line"]


def test_an_alarm_s_operator_actions_are_everyone_s(server):
    from grid_monitor.live import LIVE

    LIVE.handle(AlarmEvent(timestamp=T0, alarm_uuid="al-test", app=APP, type="init", status="Emergency", message="test"))
    with (
        server.websocket_connect("/api/islanding/ws?client_id=5103") as mine,
        server.websocket_connect("/api/islanding/ws?client_id=5104") as theirs,
    ):
        mine.receive_json(), theirs.receive_json()
        assert server.post("/api/islanding/alarms/al-test/acknowledge?client_id=5103").status_code == 200
        status = lambda m: next(a["status"] for a in m["alarms"]["alarms"] if a["uuid"] == "al-test")  # noqa: E731
        assert status(receive_until(theirs, lambda m: status(m) == "acknowledged"))  # another client sees it
    assert server.post("/api/islanding/alarms/no-such/silence?client_id=5103").status_code == 404
