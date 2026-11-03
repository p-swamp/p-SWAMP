"""The live simulation's commands and events, and the CIM edits it proposes."""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from pswamp_models.cim import CimEdit, CimEdits
from pswamp_models.common import Command
from pswamp_models.rtsim import (
    DISTURBANCES,
    OPERATIONS,
    RTSIM_COMMANDS,
    ClearShortCircuitCommand,
    FaultAndClearCommand,
    LoadStepCommand,
    OperateLineCommand,
    OperateSwitchCommand,
    ReconnectBranchCommand,
    ResetSimulationCommand,
    ShortCircuitCommand,
    SimEvent,
    TripBranchCommand,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_each_command_is_its_own_address_and_names_what_it_acts_on():
    assert OperateSwitchCommand.name == "operate.switch"
    assert TripBranchCommand.name == "trip.branch"
    assert OperateSwitchCommand(mRID="b1", open=True).mRID == "b1"
    with pytest.raises(ValidationError):
        OperateSwitchCommand(open=True)  # an operation names its object
    with pytest.raises(ValidationError):
        TripBranchCommand()


def test_operations_and_disturbances_are_told_apart():
    assert set(OPERATIONS) == {OperateSwitchCommand, OperateLineCommand}
    assert set(DISTURBANCES) == {
        TripBranchCommand,
        ReconnectBranchCommand,
        ShortCircuitCommand,
        ClearShortCircuitCommand,
        FaultAndClearCommand,
        LoadStepCommand,
    }
    assert set(RTSIM_COMMANDS) == {*OPERATIONS, *DISTURBANCES, ResetSimulationCommand}
    assert all(issubclass(command, Command) for command in RTSIM_COMMANDS)
    assert not any(command.sticky for command in RTSIM_COMMANDS)  # actions, not settings


def test_a_short_circuit_is_bolted_unless_told_otherwise():
    assert ShortCircuitCommand(mRID="node").y == 1e6
    assert ShortCircuitCommand(mRID="node", y=50).y == 50
    with pytest.raises(ValidationError):
        ShortCircuitCommand(mRID="node", y=0)


def test_a_fault_is_cleared_at_one_end_after_a_while():
    fault = FaultAndClearCommand(mRID="line")
    assert (fault.end, fault.clear_ms) == (1, 100.0)
    assert FaultAndClearCommand(mRID="line", end=2, clear_ms=80).end == 2
    for bad in ({"end": 3}, {"end": 0}, {"clear_ms": 0}, {"clear_ms": -5}):
        with pytest.raises(ValidationError):
            FaultAndClearCommand(mRID="line", **bad)


def test_a_load_step_sets_p_q_or_both_to_finite_numbers():
    assert LoadStepCommand(mRID="load", p_mw=60).q_mvar is None
    assert LoadStepCommand(mRID="load", q_mvar=-5).p_mw is None
    with pytest.raises(ValidationError):
        LoadStepCommand(mRID="load")  # a step that changes nothing
    with pytest.raises(ValidationError):
        LoadStepCommand(mRID="load", p_mw=math.inf)


def test_commands_round_trip_as_json():
    for command in (
        OperateSwitchCommand(mRID="b1", open=False, client_id="7"),
        OperateLineCommand(mRID="l1", in_service=False),
        FaultAndClearCommand(mRID="l1", end=2, clear_ms=120),
        LoadStepCommand(mRID="load", p_mw=12.5, q_mvar=3),
        ResetSimulationCommand(),
    ):
        assert type(command).model_validate_json(command.model_dump_json()) == command


def test_a_sim_event_says_what_happened_to_what_and_why():
    event = SimEvent(
        timestamp=T0, kind="trip", mRID="l1", sim_time=12.5, cause="protection", detail="overload 1.3 x limit"
    )
    assert SimEvent.topic == "sim.event"
    assert SimEvent.model_validate_json(event.model_dump_json()) == event
    with pytest.raises(ValidationError):
        SimEvent(timestamp=T0, kind="explode", mRID="l1", sim_time=0.0, cause="command")
    with pytest.raises(ValidationError):
        SimEvent(timestamp=T0, kind="trip", mRID="l1", sim_time=0.0, cause="magic")


def test_cim_edits_name_a_property_by_its_class_and_are_proposed_by_someone():
    edits = CimEdits(
        timestamp=T0,
        producer="rtsim",
        cause="command",
        sim_time=3.0,
        edits=[CimEdit(mRID="b1", attribute="Switch.open", value=True)],
        request_id="abc",
    )
    assert CimEdits.topic == "cim.edits"
    assert CimEdits.model_validate_json(edits.model_dump_json()) == edits
    for attribute in ("open", "Switch.", ".open", "Switch.open.x", "switch open"):
        with pytest.raises(ValidationError):
            CimEdit(mRID="b1", attribute=attribute, value=True)
    with pytest.raises(ValidationError):
        CimEdits(timestamp=T0, producer="rtsim", cause="command", edits=[])  # proposes nothing


def test_a_cim_edit_keeps_its_value_s_type_through_json():
    for value in (True, False, 1.5, "text"):
        edit = CimEdit(mRID="x", attribute="IdentifiedObject.name", value=value)
        assert type(CimEdit.model_validate_json(edit.model_dump_json()).value) is type(value)
