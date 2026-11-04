"""Commands to the simulation (ADR-015): an operation goes to the engine and, once it has happened, is
reported to the CIM graph as ``CimEdits``; a disturbance goes to the engine only, and is announced as a
``SimEvent``, never written to the graph."""

from __future__ import annotations

import pytest

from pswamp_core.cim import SAMPLE_GRID, CimSettings, GraphVersion, connect_reader, open_store
from pswamp_core.command_routing import CommandRefused
from pswamp_models.cim import CimEdits
from pswamp_models.rtsim import (
    ClearShortCircuitCommand,
    LoadStepCommand,
    OperateLineCommand,
    OperateSwitchCommand,
    ReconnectBranchCommand,
    ResetSimulationCommand,
    ShortCircuitCommand,
    SimEvent,
    TripBranchCommand,
)
from pswamp_modules.rtsim_from_cim.follow import Controller

SETTINGS = CimSettings(cim_path=SAMPLE_GRID)
P = "3f5e0000-0000-4000-8000-0000000000"
BAY_BREAKER, ALPHA_BETA, LOAD, TRANSFORMER = P + "a1", P + "24", P + "33", P + "35"


@pytest.fixture(scope="module")
def repo():
    return connect_reader(SETTINGS)


@pytest.fixture
def controller(repo):
    controller = Controller(repo, GraphVersion(open_store(SETTINGS)), dt=0.01)
    controller.sent = []
    controller.attach(controller.sent.append)
    return controller


def a_frame_ran(controller, rejected=()) -> None:
    """What the engine sends after a frame: its state, one frame on."""
    runner = controller.runner
    controller.receive(("state", runner.build, runner.frame + 1, runner.sol.t + 0.02, runner.sol.y, runner.sol.v, list(rejected)))


def events(controller) -> list[tuple]:
    return [message[1] for message in controller.sent if message[0] == "event"]


def test_a_breaker_operated_is_announced_then_reported_to_the_graph_once_a_frame_ran(controller):
    command = OperateSwitchCommand(mRID=BAY_BREAKER, open=True)
    (event,) = controller.command(command)
    assert isinstance(event, SimEvent) and (event.kind, event.mRID, event.cause) == ("open", BAY_BREAKER, "command")
    assert event.request_id == command.request_id
    assert events(controller) == [("switches", "Switch", "Alpha-Gamma bay breaker", "open", {})]
    assert controller.reports() == []  # the engine has not applied it yet
    a_frame_ran(controller)
    (edits,) = controller.reports()
    assert isinstance(edits, CimEdits) and (edits.producer, edits.cause, edits.request_id) == ("rtsim", "command", command.request_id)
    assert [(e.mRID, e.attribute, e.value) for e in edits.edits] == [(BAY_BREAKER, "Switch.open", True)]
    assert controller.reports() == []  # once


def test_a_breaker_already_in_that_state_is_refused(controller):
    with pytest.raises(CommandRefused, match="already closed"):
        controller.command(OperateSwitchCommand(mRID=BAY_BREAKER, open=False))
    assert controller.sent == []


def test_a_line_without_a_breaker_is_operated_by_its_terminal(controller):
    command = OperateLineCommand(mRID=ALPHA_BETA, in_service=False)
    controller.command(command)
    assert events(controller) == [("lines", "Line", "Alpha-Beta 400 kV line", "disconnect", {})]
    a_frame_ran(controller)
    (edits,) = controller.reports()
    terminal = next(t for t in controller.live.exporter.repo.from_mRID(ALPHA_BETA).Terminals if t.sequenceNumber == 1)
    assert [(e.mRID, e.attribute, e.value) for e in edits.edits] == [(terminal.mRID, "ACDCTerminal.connected", False)]
    controller.sent.clear()
    controller.command(OperateLineCommand(mRID=ALPHA_BETA, in_service=True))
    a_frame_ran(controller)
    (back,) = controller.reports()
    every = {t.mRID for t in controller.live.exporter.repo.from_mRID(ALPHA_BETA).Terminals}
    assert {e.mRID for e in back.edits} == every and all(e.value is True for e in back.edits)


def test_a_transformer_without_a_breaker_is_operated_by_its_terminal_too(controller):
    # The page draws transformers as branches, and offers to take one out: by its terminal, as a line.
    (name,) = controller.sim.ids["transformers"]
    controller.command(OperateLineCommand(mRID=TRANSFORMER, in_service=False))
    assert events(controller) == [("trafos", "Trafo", name, "disconnect", {})]
    a_frame_ran(controller)
    (edits,) = controller.reports()
    terminal = next(t for t in controller.live.exporter.repo.from_mRID(TRANSFORMER).Terminals if t.sequenceNumber == 1)
    assert [(e.mRID, e.attribute, e.value) for e in edits.edits] == [(terminal.mRID, "ACDCTerminal.connected", False)]


def test_an_operation_the_engine_rejected_is_not_reported(controller):
    controller.command(OperateLineCommand(mRID=ALPHA_BETA, in_service=False))
    (sent,) = events(controller)
    a_frame_ran(controller, rejected=[(sent, "refused")])
    assert controller.reports() == []


def test_a_line_trip_is_a_disturbance_the_graph_never_hears_of(controller):
    (event,) = controller.command(TripBranchCommand(mRID=ALPHA_BETA))
    assert (event.kind, event.cause) == ("trip", "disturbance")
    assert events(controller) == [("lines", "Line", "Alpha-Beta 400 kV line", "disconnect", {})]
    a_frame_ran(controller)
    assert controller.reports() == []
    controller.command(ReconnectBranchCommand(mRID=ALPHA_BETA))
    assert events(controller)[-1] == ("lines", "Line", "Alpha-Beta 400 kV line", "connect", {})


def test_a_transformer_trips_too(controller):
    (name,) = controller.sim.ids["transformers"]
    controller.command(TripBranchCommand(mRID=TRANSFORMER))
    assert events(controller) == [("trafos", "Trafo", name, "disconnect", {})]


def test_a_short_circuit_is_at_the_bus_of_a_node(controller):
    node, bus = next(iter(controller.sim.ids["node_to_bus"].items()))
    (event,) = controller.command(ShortCircuitCommand(mRID=node, y=50.0))
    assert (event.kind, event.cause) == ("short_circuit", "disturbance")
    assert events(controller) == [("buses", "", bus, "short_circuit", {"y": 50.0})]
    controller.command(ClearShortCircuitCommand(mRID=node))
    assert events(controller)[-1] == ("buses", "", bus, "clear_short_circuit", {})


def test_a_load_step_sets_what_it_names(controller):
    name = {mrid: name for name, mrid in controller.sim.ids["loads"].items()}[LOAD]
    (event,) = controller.command(LoadStepCommand(mRID=LOAD, p_mw=60.0))
    assert (event.kind, event.cause) == ("load_step", "disturbance")
    assert events(controller) == [("loads", "Load", name, "set_power", {"P": 60.0})]


@pytest.mark.parametrize(
    "command",
    [
        OperateSwitchCommand(mRID=ALPHA_BETA, open=True),  # a line, not a switch
        OperateLineCommand(mRID=BAY_BREAKER, in_service=False),
        TripBranchCommand(mRID=LOAD),
        ShortCircuitCommand(mRID="nowhere"),
        LoadStepCommand(mRID=ALPHA_BETA, p_mw=1.0),
    ],
    ids=lambda command: command.name,
)
def test_a_command_on_the_wrong_object_is_refused(controller, command):
    with pytest.raises(CommandRefused):
        controller.command(command)
    assert controller.sent == []


def test_a_reset_starts_the_simulation_over_from_the_graph(controller):
    controller.command(TripBranchCommand(mRID=ALPHA_BETA))
    (event,) = controller.command(ResetSimulationCommand())
    assert event.kind == "reset"
    kind, build, *_ = controller.sent[-1]
    assert (kind, build) == ("build", 1)  # the export, as the graph has it: no trip in it
