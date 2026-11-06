"""The engine's process: what comes down its link (from the controller's ``LiveTops``) is applied
before the next frame; its state goes back up the link, a frame at a time; and the controller going
away leaves the simulation running."""

from __future__ import annotations

import multiprocessing
import time

import numpy as np
import pytest
from lazycim.sim import get_exporter

from pswamp_core.cim import SAMPLE_GRID, CimSettings, connect_reader
from pswamp_modules.rtsim_from_cim.engine import EXPORT
from pswamp_modules.rtsim_from_cim.pmu import read_measurements
from pswamp_modules.rtsim_from_cim.process import EngineProcess

SETTINGS = CimSettings(cim_path=SAMPLE_GRID)


class Received:
    """What the engine sent up, read until a condition holds."""

    def __init__(self, engine: EngineProcess) -> None:
        self.engine, self.frames, self.logs, self.headers, self.scans = engine, [], [], 0, []

    def until(self, condition, timeout: float = 60.0) -> None:
        deadline = time.monotonic() + timeout
        while not condition():
            assert time.monotonic() < deadline, "timed out"
            for kind, *message in self.engine.receive():
                if kind == "error":
                    raise message[0]
                if kind == "log":
                    self.logs.append(message[0])
                elif kind == "frame":
                    self.frames.append(message[1])
                elif kind == "header":
                    self.header, self.headers = message[0], self.headers + 1
                elif kind == "scan":
                    self.scans.append(message)

    def angles(self) -> np.ndarray:
        values = np.array([v for v, m in zip(self.frames[-1], self.header.measurement, strict=True) if m == "V_Angle"], dtype=float)
        return values - values[0]


def states(link, timeout: float = 10.0) -> list[tuple]:
    """What came up the link so far, waiting for at least one."""
    assert link.poll(timeout)
    found = []
    while link.poll():
        found.append(link.recv())
    return found


@pytest.fixture
def engine():
    repo = connect_reader(SETTINGS)
    sim = get_exporter("tops", repo, **EXPORT).build()
    ours, theirs = multiprocessing.get_context("spawn").Pipe()
    engine = EngineProcess(sim.model, dt=0.01, rate=50.0, steps=2, measurements=read_measurements(repo), ids=sim.ids, link=theirs)
    yield engine, ours, sim
    ours.close()
    engine.close()


def test_scada_is_scanned_at_the_first_frame_then_every_period_of_the_simulation_s_clock():
    repo = connect_reader(SETTINGS)
    sim = get_exporter("tops", repo, **EXPORT).build()
    engine = EngineProcess(sim.model, dt=0.01, rate=50.0, steps=2, measurements=read_measurements(repo), ids=sim.ids, scada_period=0.2)
    try:
        seen = Received(engine)
        seen.until(lambda: len(seen.scans) >= 4)
    finally:
        engine.close()
    times = [sim_time for _, sim_time, _, _ in seen.scans]
    assert times[0] == pytest.approx(0.02)  # the first frame
    assert np.allclose(np.diff(times), 0.2, atol=0.021)  # then every 0.2 s of simulated time
    _, _, analogs, discretes = seen.scans[-1]
    assert len(analogs) == 28 and {value for _, value in discretes} == {1}


def test_no_period_no_scan(engine):
    engine, _, _ = engine
    seen = Received(engine)
    seen.until(lambda: len(seen.frames) >= 25)
    assert seen.scans == []


def test_its_state_comes_up_the_link_a_frame_at_a_time(engine):
    engine, link, _ = engine
    seen = Received(engine)
    seen.until(lambda: len(seen.frames) >= 25)
    kind, build, frame, t, y, v, rejected = states(link)[-1]
    assert (kind, build, rejected) == ("state", 0, [])
    assert frame >= 1 and t == pytest.approx(frame * 0.02) and np.isfinite(y).all() and len(v) > 0


def test_an_event_down_the_link_shows_in_the_next_frames(engine):
    engine, link, _ = engine
    seen = Received(engine)
    seen.until(lambda: len(seen.frames) >= 25)
    before = seen.angles()
    link.send(("event", ("switches", "Switch", "Alpha-Gamma bay breaker", "open", {})))
    then = len(seen.frames)
    seen.until(lambda: len(seen.frames) >= then + 25)
    assert np.max(np.abs(seen.angles() - before)) > 0.1  # the flow went round the other way


def test_what_the_engine_cannot_apply_comes_back_rejected(engine):
    engine, link, _ = engine
    states(link)
    unknown = ("switches", "Switch", "unknown", "open", {})
    link.send(("event", unknown))
    rejected, deadline = [], time.monotonic() + 10
    while time.monotonic() < deadline:
        rejected = [r for state in states(link) for r in state[6]]
        if rejected:
            break
    ((what, why),) = rejected
    assert what == unknown and "unknown" in why


def test_a_model_sent_whole_is_built_again_with_a_new_header(engine):
    engine, link, sim = engine
    seen = Received(engine)
    seen.until(lambda: len(seen.frames) >= 10)
    link.send(("build", 1, sim.model, sim.ids))
    seen.until(lambda: seen.headers >= 2)
    deadline = time.monotonic() + 10
    while not any(state[1] == 1 for state in states(link)):
        assert time.monotonic() < deadline, "no state of the new build"
    then = len(seen.frames)
    seen.until(lambda: len(seen.frames) >= then + 10)


def test_the_controller_gone_the_simulation_goes_on(engine):
    engine, link, _ = engine
    seen = Received(engine)
    seen.until(lambda: len(seen.frames) >= 5)
    link.close()
    seen.until(lambda: "the simulation is no longer steered" in seen.logs, timeout=5)
    then = len(seen.frames)
    seen.until(lambda: len(seen.frames) >= then + 25)
