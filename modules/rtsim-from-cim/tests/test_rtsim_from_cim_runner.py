"""``RemoteRunner``: LazyCIM's ``LiveTops`` steering a simulation stepped elsewhere. What it does to
its shadow of the system goes down as messages; the state the engine sends back is what it reads."""

from __future__ import annotations

import numpy as np
import pytest
from lazycim.sim.tops_live import LiveTops

from pswamp_core.cim import SAMPLE_GRID, CimSettings, connect_reader
from pswamp_modules.rtsim_from_cim.engine import EXPORT, SimEngine
from pswamp_modules.rtsim_from_cim.runner import RemoteRunner

SETTINGS = CimSettings(cim_path=SAMPLE_GRID)
BAY_BREAKER = "3f5e0000-0000-4000-8000-0000000000a1"
ALPHA_GAMMA = "3f5e0000-0000-4000-8000-000000000026"


@pytest.fixture(scope="module")
def repo():
    return connect_reader(SETTINGS)


class Link:
    """The engine's end, played by hand: what the runner sends, and a real engine to answer with."""

    def __init__(self, live: LiveTops) -> None:
        self.sent: list[tuple] = []
        self.engine = SimEngine(live.built.model, dt=live.dt, events=live.built.events)
        self.frame, self.build = 0, 0

    def send(self, message: tuple) -> None:
        self.sent.append(message)

    def run(self, runner: RemoteRunner, frames: int = 1, rejected=()) -> None:
        """Apply what was sent, step ``frames`` frames of 2 steps, and send the state back."""
        rejected = list(rejected)
        for message in self.sent:
            if message[0] == "build":
                self.build = message[1]
                self.engine.rebuild(message[2], message[4])
            else:
                try:
                    self.engine.apply(message)
                except (KeyError, ValueError) as error:
                    rejected.append((message[1], str(error)))
        self.sent.clear()
        for _ in range(frames):
            self.engine.step(2)
            self.frame += 1
        runner.receive(("state", self.build, self.frame, *self.engine.state(), rejected))


@pytest.fixture
def live(repo):
    return LiveTops.from_repo(repo, dt=0.01, **EXPORT)


@pytest.fixture
def link(live):
    return Link(live)


def test_live_tops_reads_the_state_the_engine_sends(live, link):
    runner = RemoteRunner(live, link.send)
    assert live.simulator is runner and live.time == 0.0
    link.run(runner, frames=50)
    assert live.time == pytest.approx(1.0)  # 50 frames of 2 steps of 10 ms
    # read off the engine's state, through the shadow's model: the 400 kV and the 132 kV buses, in
    # whatever order the store lists the nodes (it varies with what else a test session wrote to it)
    kvs = sorted(live.voltage(node)[0] for node in live.sim.ids["node_to_bus"])
    assert 120 < kvs[0] < 145 and 300 < kvs[-1] < 450


def test_a_switch_opened_through_live_tops_goes_to_the_engine_and_is_a_change_once_a_frame_ran(live, link):
    runner = RemoteRunner(live, link.send)
    link.run(runner)
    assert live.open(BAY_BREAKER)
    (event,) = link.sent
    assert event == ("event", ("switches", "Switch", "Alpha-Gamma bay breaker", "open", {}))
    assert live.is_open(BAY_BREAKER)  # the shadow knows at once
    assert live.cim_changes() == []  # the engine has not applied it yet
    link.run(runner, frames=50)
    ((mrid, prop, value, _),) = live.cim_changes()
    assert (mrid, prop, value) == (BAY_BREAKER, "Switch.open", True)
    assert abs(live.current(ALPHA_GAMMA, end=1)) < 1.0  # amperes: the engine's line is cut off


def test_a_command_the_engine_rejected_is_no_change(live, link):
    runner = RemoteRunner(live, link.send)
    link.run(runner)
    live.open(BAY_BREAKER)
    (sent,) = link.sent
    link.sent.clear()  # lost on the way: the engine says it could not apply it
    link.run(runner, rejected=[(sent[1], "refused")])
    assert live.cim_changes() == []


def test_a_command_the_shadow_refuses_never_leaves(live, link):
    runner = RemoteRunner(live, link.send)
    with pytest.raises(KeyError):
        runner.submit("switches", "Switch", "unknown", "open")
    assert link.sent == []


def test_an_input_set_on_the_shadow_goes_to_the_engine(live, link):
    RemoteRunner(live, link.send)
    gen = live.ps.dyn_mdls_dict["gen"]["GEN"]
    gen.set_input("P_m", 0.5, 0)  # what LazyCIM does for a machine's power with no governor
    assert link.sent == [("input", ("gen", "GEN", "P_m", 0.5, 0))]
    assert gen._input_values["P_m"][0] == 0.5  # and the shadow has it too


def test_the_state_of_an_earlier_build_is_ignored(live, link):
    runner = RemoteRunner(live, link.send)
    link.run(runner, frames=10)
    runner.rebuild(live)
    assert link.sent[-1][:2] == ("build", 1)
    stale = ("state", 0, 99, 5.0, link.engine.state()[1], link.engine.state()[2], [])
    runner.receive(stale)
    assert runner.sol.t == 0.0 and runner.frame == 10


def test_states_overwrite_one_another_and_keep_every_rejection(live, link):
    runner = RemoteRunner(live, link.send)
    _, y, v = link.engine.state()
    runner.receive(("state", 0, 1, 0.02, y, v, [("a", "x")]))
    runner.receive(("state", 0, 2, 0.04, y, v, [("b", "y")]))
    assert runner.frame == 2 and runner.sol.t == 0.04 and [e for e, _ in runner.rejected] == ["a", "b"]
    assert np.array_equal(runner.sol.v, v)
