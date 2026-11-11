"""Following the graph: an edit in the store becomes, through ``LiveTops``, what the engine is sent,
once the stamp says the graph changed; and nothing is read before."""

from __future__ import annotations

import time

import pytest

from pswamp_core.cim import SAMPLE_GRID, CimSettings, GraphVersion, connect_reader, open_store, stage
from pswamp_core.cim.testing import edit, reset
from pswamp_core.command_routing import CommandRefused
from pswamp_models.rtsim import OperateLineCommand, ResetSimulationCommand, TripBranchCommand
from pswamp_modules.rtsim_from_cim.follow import Controller

SETTINGS = CimSettings(cim_path=SAMPLE_GRID)
P = "3f5e0000-0000-4000-8000-0000000000"
BAY_BREAKER, ALPHA_BETA, LOAD, TRANSFORMER = P + "a1", P + "24", P + "33", P + "35"

needs_profiles = pytest.mark.skipif(not stage(SETTINGS).writable, reason="the CGMES vocabularies are not available to LazyCIM")


@pytest.fixture
def controller():
    controller = Controller(connect_reader(SETTINGS), GraphVersion(open_store(SETTINGS)), dt=0.01)
    controller.sent = []
    controller.attach(controller.sent.append)
    yield controller
    reset(SETTINGS)


def events(controller) -> list[tuple]:
    return [what for kind, what in (m[:2] for m in controller.sent) if kind == "event"]


def test_nothing_changed_is_nothing_read_but_the_stamp(controller):
    time.sleep(0.3)  # nothing expires on a timer
    with controller.live.exporter.repo.measure() as work:
        assert controller.changes() == []
    assert work.queries == 0 and controller.sent == []  # the stamp is asked of the store, not the repository


@needs_profiles
def test_a_breaker_opened_in_the_graph_is_a_switch_opened_in_the_engine(controller):
    edit(SETTINGS, BAY_BREAKER, open=True)
    said = controller.changes()
    assert events(controller) == [("switches", "Switch", "Alpha-Gamma bay breaker", "open", {})]
    assert said == ["switch Alpha-Gamma bay breaker opened"]
    controller.sent.clear()
    edit(SETTINGS, BAY_BREAKER, open=False)
    controller.changes()
    assert events(controller) == [("switches", "Switch", "Alpha-Gamma bay breaker", "close", {})]


@needs_profiles
def test_a_load_that_draws_more_is_its_power_set(controller):
    name = {mrid: name for name, mrid in controller.live.sim.ids["loads"].items()}[LOAD]
    edit(SETTINGS, LOAD, p=150.0)
    controller.changes()
    assert events(controller) == [("loads", "Load", name, "set_power", {"P": 150.0})]


@needs_profiles
def test_a_terminal_disconnected_takes_its_line_out_live(controller):
    terminal = next(t.mRID for t in controller.live.exporter.repo.from_mRID(ALPHA_BETA).Terminals if t.sequenceNumber == 1)
    edit(SETTINGS, terminal, connected=False)
    controller.changes()
    assert events(controller) == [("lines", "Line", "Alpha-Beta 400 kV line", "disconnect", {})]
    controller.sent.clear()
    edit(SETTINGS, terminal, connected=True)
    controller.changes()
    assert events(controller) == [("lines", "Line", "Alpha-Beta 400 kV line", "connect", {})]


def _cut_off_gamma_132(controller) -> str:
    """Take Gamma's 132 kV side off the grid: it hangs off its transformer alone, with a load on it.
    Returns the transformer's first terminal, the one disconnected."""
    terminal = next(t.mRID for t in controller.live.exporter.repo.from_mRID(TRANSFORMER).Terminals if t.sequenceNumber == 1)
    edit(SETTINGS, terminal, connected=False)
    return terminal


@needs_profiles
def test_a_part_cut_off_while_running_is_an_island_that_runs_on(controller):
    # The graph says the transformer is out: the slack bus no longer reaches Gamma's 132 kV side, a
    # change the running simulation takes as it is, with no build, and the island stays in it.
    _cut_off_gamma_132(controller)
    said = controller.changes()
    assert not any("built again" in line for line in said)
    name = {mrid: name for name, mrid in controller.sim.ids["transformers"].items()}[TRANSFORMER]
    assert events(controller) == [("trafos", "Trafo", name, "disconnect", {})]
    assert controller.sim.ids["de_energised"] and controller.live.left_out == {}
    assert not any(message[0] == "build" for message in controller.sent)
    controller.sent.clear()
    controller.command(TripBranchCommand(mRID=TRANSFORMER))  # still a branch of the simulation
    assert events(controller) == [("trafos", "Trafo", name, "disconnect", {})]


@needs_profiles
def test_a_part_left_out_at_a_build_says_why_and_comes_back_with_a_build(controller):
    # Cut off when the system is built, with a load on it, the part cannot be initialised: it is left
    # out, and a command on it says so. The graph joining it again builds the system again.
    runner = controller.runner
    terminal = _cut_off_gamma_132(controller)
    controller.changes()
    controller.command(ResetSimulationCommand())  # built from the graph: the part is cut off
    assert controller.live.left_out.get("transformers")
    kind, build, model, ids, built_events = controller.sent[-1]
    assert (kind, build) == ("build", 1) and TRANSFORMER in ids["transformers"].values()
    _, y, v = runner.sol.t, runner.sol.y, runner.sol.v
    runner.receive(("state", 1, 100, 2.0, y, v, []))  # two seconds into the run
    for command in (OperateLineCommand(mRID=TRANSFORMER, in_service=True), TripBranchCommand(mRID=TRANSFORMER)):
        with pytest.raises(CommandRefused, match="left out when it was built"):
            controller.command(command)
    edit(SETTINGS, terminal, connected=True)
    said = controller.changes()
    assert any("built again" in line for line in said)
    assert controller.sent[-1][:2] == ("build", 2) and controller.live.left_out == {}
    assert controller.live.time == pytest.approx(2.0)  # the clock runs on from where the engine was
