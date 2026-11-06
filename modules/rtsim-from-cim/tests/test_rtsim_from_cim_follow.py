"""Following the graph: an edit in the store becomes, through ``LiveTops``, what the engine is sent,
once the stamp says the graph changed; and nothing is read before."""

from __future__ import annotations

import time

import pytest

from pswamp_core.cim import SAMPLE_GRID, CimSettings, GraphVersion, connect_reader, open_store, stage
from pswamp_core.cim.testing import edit, reset
from pswamp_core.command_routing import CommandRefused
from pswamp_models.rtsim import OperateSwitchCommand, TripBranchCommand
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


@needs_profiles
def test_a_part_cut_off_is_a_model_built_again_the_clock_running_on(controller):
    # Gamma's 132 kV side hangs off its transformer alone: taken out, it is left out of the model
    # (de-energised), which a running simulation cannot absorb.
    runner = controller.runner
    _, y, v = runner.sol.t, runner.sol.y, runner.sol.v
    runner.receive(("state", 0, 100, 2.0, y, v, []))  # two seconds into the run
    terminal = next(t.mRID for t in controller.live.exporter.repo.from_mRID(TRANSFORMER).Terminals if t.sequenceNumber == 1)
    edit(SETTINGS, terminal, connected=False)
    said = controller.changes()
    assert any("built again" in line for line in said)
    kind, build, model, ids = controller.sent[-1]
    assert (kind, build) == ("build", 1) and ids["de_energised"]
    assert controller.live.time == pytest.approx(2.0)  # the clock runs on from where the engine was


@needs_profiles
def test_a_command_on_what_the_simulation_left_out_says_why(controller):
    terminal = next(t.mRID for t in controller.live.exporter.repo.from_mRID(TRANSFORMER).Terminals if t.sequenceNumber == 1)
    edit(SETTINGS, terminal, connected=False)
    controller.changes()
    with pytest.raises(CommandRefused, match="slack bus cannot reach"):
        controller.command(OperateSwitchCommand(mRID=TRANSFORMER, open=False))
    with pytest.raises(CommandRefused, match="slack bus cannot reach"):
        controller.command(TripBranchCommand(mRID=TRANSFORMER))
