"""The engine's process: what comes down its ``changes`` pipe (from a follower in another process) is
applied before the next frame, and the follower going away leaves the simulation running."""

from __future__ import annotations

import multiprocessing
import time

import numpy as np
import pytest

from pswamp_core.cim import SAMPLE_GRID, CimSettings, GraphVersion, connect_reader, open_store
from pswamp_modules.rtsim_from_cim.engine import Change
from pswamp_modules.rtsim_from_cim.follow import Follower
from pswamp_modules.rtsim_from_cim.pmu import read_analogs
from pswamp_modules.rtsim_from_cim.process import EngineProcess

SETTINGS = CimSettings(cim_path=SAMPLE_GRID)
BAY_BREAKER = "3f5e0000-0000-4000-8000-0000000000a1"


def row_of(ids: dict, mrid: str) -> str:
    """The model's row name for ``mrid``."""
    return next(name for group in ids.values() if isinstance(group, dict) for name, m in group.items() if m == mrid)


class Received:
    """What the engine sent up, read until a condition holds."""

    def __init__(self, engine: EngineProcess) -> None:
        self.engine, self.frames, self.logs = engine, [], []

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
                    self.header = message[0]

    def angles(self) -> np.ndarray:
        values = np.array([v for v, m in zip(self.frames[-1], self.header.measurement, strict=True) if m == "V_Angle"], dtype=float)
        return values - values[0]


@pytest.fixture
def engine():
    follower = Follower(connect_reader(SETTINGS), GraphVersion(open_store(SETTINGS)))
    read, write = multiprocessing.get_context("spawn").Pipe(duplex=False)
    engine = EngineProcess(
        follower.sim.model,
        open_switches=follower.open_switches,
        dt=0.01,
        rate=50.0,
        steps=2,
        analogs=read_analogs(follower.exporter.repo),
        ids=follower.sim.ids,
        changes=read,
    )
    yield engine, write, follower.sim.ids
    write.close()
    engine.close()


def test_a_change_down_the_pipe_shows_in_the_next_frames(engine):
    engine, changes, ids = engine
    seen = Received(engine)
    seen.until(lambda: len(seen.frames) >= 25)
    before = seen.angles()
    name = row_of(ids, BAY_BREAKER)
    changes.send(Change(opened=frozenset({name})))
    seen.until(lambda: f"{name} disconnected" in seen.logs, timeout=5)
    then = len(seen.frames)
    seen.until(lambda: len(seen.frames) >= then + 25)
    assert np.max(np.abs(seen.angles() - before)) > 0.1  # the flow went round the other way


def test_the_follower_gone_the_simulation_goes_on(engine):
    engine, changes, _ = engine
    seen = Received(engine)
    seen.until(lambda: len(seen.frames) >= 5)
    changes.close()
    seen.until(lambda: "the graph is no longer followed" in seen.logs, timeout=5)
    then = len(seen.frames)
    seen.until(lambda: len(seen.frames) >= then + 25)
