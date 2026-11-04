"""The CIM graph app writes what a producer reports (ADR-015): the live simulation's ``CimEdits``,
for the properties it is allowed, in one update, and the state they lead to is pushed to every socket.
Over the three-substation sample grid, in an in-process store."""

from __future__ import annotations

import time

import pytest
from test_cim_graph import ALPHA_BETA, BAY_BREAKER, COUPLER, SETTINGS, needs_profiles, next_state, server  # noqa: F401

from pswamp_models.cim import CimEdit, CimEdits
from pswamp_core.util.time import utcnow


def edits(*edits: tuple[str, str, object], producer: str = "rtsim") -> CimEdits:
    return CimEdits(
        timestamp=utcnow(),
        producer=producer,
        cause="command",
        edits=[CimEdit(mRID=mrid, attribute=attribute, value=value) for mrid, attribute, value in edits],
    )


@pytest.fixture
def writer(monkeypatch):
    monkeypatch.delenv("PSWAMP_CIM_URL", raising=False)
    from cim_graph.grid import Writer

    writer = Writer(SETTINGS)
    writer.state()
    yield writer
    writer.reset()


@needs_profiles
def test_a_reported_switch_is_written_in_one_update(writer):
    with writer.repo.measure() as work:
        done = writer.apply(edits((BAY_BREAKER, "Switch.open", True)))
    assert work.write_calls == 1 and done == [f"{BAY_BREAKER} Switch.open = True"]
    assert writer.state().switches[BAY_BREAKER] is True


@needs_profiles
def test_a_reported_terminal_takes_its_line_out(writer):
    terminal = next(t.mRID for t in writer.repo.from_mRID(ALPHA_BETA).Terminals if t.sequenceNumber == 1)
    writer.apply(edits((terminal, "ACDCTerminal.connected", False)))
    assert ALPHA_BETA in writer.state().out_of_service


@needs_profiles
def test_what_a_producer_may_not_write_is_refused_whole(writer):
    with pytest.raises(PermissionError, match="nobody"):
        writer.apply(edits((COUPLER, "Switch.open", True), producer="nobody"))
    with pytest.raises(PermissionError, match="Switch.normalOpen"):
        writer.apply(edits((COUPLER, "Switch.open", True), (BAY_BREAKER, "Switch.normalOpen", True)))
    assert writer.state().switches == {COUPLER: False, BAY_BREAKER: False}  # neither was written


@needs_profiles
def test_an_object_that_is_not_there_is_refused(writer):
    with pytest.raises(LookupError):
        writer.apply(edits(("nowhere", "Switch.open", True)))
    with pytest.raises(LookupError, match="no Switch.open"):
        writer.apply(edits((ALPHA_BETA, "Switch.open", True)))  # a line has no such property


@needs_profiles
def test_what_the_simulation_reports_on_the_transport_reaches_every_socket(server):  # noqa: F811
    import functools

    from cim_graph.api import SIMULATION
    from shared import transport

    app, source = SIMULATION
    with server.websocket_connect("/api/cim-graph/ws?client_id=301") as ws:
        ws.receive_json()
        time.sleep(0.2)  # the app's subscription is received
        report = edits((BAY_BREAKER, "Switch.open", True))
        server.portal.call(functools.partial(transport().publish, report, app=app, key=f"live.{source}"))
        state = next_state(ws, lambda s: s["switches"][BAY_BREAKER])
        assert state["out_of_service"] == ["3f5e0000-0000-4000-8000-000000000026"]
