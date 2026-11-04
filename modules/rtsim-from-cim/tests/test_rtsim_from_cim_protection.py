"""The simulation's protection: a fault cleared by the breakers that isolate its line, at the time it
was asked for; and a line carrying more than its limit tripped after an inverse time, as its relay
would. The breakers it opens are said as ``CimEdits``, like an operator's; the fault never is."""

from __future__ import annotations

import math

import pytest

from pswamp_core.cim import SAMPLE_GRID, CimSettings, GraphVersion, connect_reader, open_store
from pswamp_core.command_routing import CommandRefused
from pswamp_models.cim import CimEdits
from pswamp_models.rtsim import FaultAndClearCommand, SimEvent
from pswamp_modules.rtsim_from_cim.follow import Controller
from pswamp_modules.rtsim_from_cim.protection import Overload, ProtectionSettings, trip_time

SETTINGS = CimSettings(cim_path=SAMPLE_GRID)
P = "3f5e0000-0000-4000-8000-0000000000"
BAY_BREAKER, ALPHA_BETA, ALPHA_GAMMA = P + "a1", P + "24", P + "26"


# -- the curve -------------------------------------------------------------------------------


def test_the_inverse_time_curve_is_iec_standard_inverse():
    assert trip_time(2.0, tms=1.0) == pytest.approx(0.14 / (2.0**0.02 - 1))  # about 10 s
    assert trip_time(1.3, tms=0.5) == pytest.approx(0.5 * 0.14 / (1.3**0.02 - 1))
    assert trip_time(4.0, tms=1.0) < trip_time(2.0, tms=1.0)  # more current, sooner
    assert math.isinf(trip_time(1.0, tms=1.0)) and math.isinf(trip_time(0.5, tms=1.0))  # never below pickup


def test_an_overload_trips_once_its_time_is_spent_and_resets_below_pickup():
    overload = Overload(ProtectionSettings(pickup=1.0, tms=0.5))
    time = trip_time(2.0, tms=0.5)
    assert overload.check(0.0, [("L", 1, 200.0, 100.0)]) == []
    assert overload.check(time * 0.6, [("L", 1, 200.0, 100.0)]) == []
    assert overload.check(time * 0.7, [("L", 1, 50.0, 100.0)]) == []  # back under: it starts over
    assert overload.check(time * 1.3, [("L", 1, 200.0, 100.0)]) == []
    ((line, end, ratio),) = overload.check(time * 1.75, [("L", 1, 200.0, 100.0)])
    assert (line, end, ratio) == ("L", 1, pytest.approx(2.0))
    assert overload.check(time * 1.8, [("L", 1, 200.0, 100.0)]) == []  # tripped once, starting over


# -- in the controller -----------------------------------------------------------------------


@pytest.fixture(scope="module")
def repo():
    return connect_reader(SETTINGS)


def controller_of(repo, **protection) -> Controller:
    controller = Controller(repo, GraphVersion(open_store(SETTINGS)), dt=0.01, protection=ProtectionSettings(**protection))
    controller.sent = []
    controller.attach(controller.sent.append)
    return controller


def time_passes(controller, seconds: float, frames: int = 1) -> None:
    runner = controller.runner
    controller.receive(("state", runner.build, runner.frame + frames, runner.sol.t + seconds, runner.sol.y, runner.sol.v, []))


def test_a_fault_is_put_on_now_and_cleared_by_the_engine_on_time(repo):
    controller = controller_of(repo)
    command = FaultAndClearCommand(mRID=ALPHA_GAMMA, end=1, clear_ms=80)
    (event,) = controller.command(command)
    assert (event.kind, event.cause, event.mRID) == ("short_circuit", "disturbance", ALPHA_GAMMA)
    (now, later) = controller.sent
    assert now[0] == "event" and now[1][:2] == ("buses", "") and now[1][3:] == ("short_circuit", {"y": 1e6})
    kind, at, messages = later
    assert kind == "at" and at == pytest.approx(0.08)  # on the engine's clock
    assert ("event", ("switches", "Switch", "Alpha-Gamma bay breaker", "open", {})) in messages
    assert messages[-1] == ("event", ("buses", "", now[1][2], "clear_short_circuit", {}))


def test_once_the_fault_is_cleared_the_breakers_it_opened_are_said_for_the_graph(repo):
    controller = controller_of(repo)
    controller.command(FaultAndClearCommand(mRID=ALPHA_GAMMA, end=1, clear_ms=80))
    time_passes(controller, 0.04)
    assert controller.reports() == []  # not yet cleared
    time_passes(controller, 0.06)
    said = [(e.kind, e.cause, e.mRID) for e in controller.reports() if isinstance(e, SimEvent)]
    assert said == [("open", "protection", BAY_BREAKER), ("trip", "protection", ALPHA_GAMMA)]
    time_passes(controller, 0.02)
    (edits,) = [m for m in controller.reports() if isinstance(m, CimEdits)]
    assert (edits.cause, edits.edits[0].mRID, edits.edits[0].value) == ("protection", BAY_BREAKER, True)


def test_a_fault_on_what_is_not_a_line_is_refused(repo):
    controller = controller_of(repo)
    with pytest.raises(CommandRefused):
        controller.command(FaultAndClearCommand(mRID=BAY_BREAKER))


def test_a_line_over_its_limit_is_tripped_by_its_breakers(repo):
    controller = controller_of(repo, tms=0.05)
    current = abs(controller.live.current(ALPHA_GAMMA, end=1))
    controller.limits = {(ALPHA_GAMMA, 1): current / 2}  # the sample grid has no limits: twice over this one
    time_passes(controller, 0.0)
    assert controller.reports() == []
    time_passes(controller, trip_time(2.0, tms=0.05) + 0.1)
    said = controller.reports()
    (trip,) = [m for m in said if isinstance(m, SimEvent) and m.kind == "trip"]
    assert (trip.cause, trip.mRID) == ("protection", ALPHA_GAMMA) and "overload" in trip.detail
    assert ("event", ("switches", "Switch", "Alpha-Gamma bay breaker", "open", {})) in controller.sent
    time_passes(controller, 0.02)
    (edits,) = [m for m in controller.reports() if isinstance(m, CimEdits)]
    assert (edits.cause, edits.edits[0].mRID) == ("protection", BAY_BREAKER)


def test_a_line_over_its_limit_at_both_ends_is_tripped_once(repo):
    controller = controller_of(repo, tms=0.05)
    ends = {end: abs(controller.live.current(ALPHA_BETA, end=end)) for end in (1, 2)}
    controller.limits = {(ALPHA_BETA, end): current / 2 for end, current in ends.items()}  # both relays run out together
    time_passes(controller, 0.0)
    controller.reports()
    time_passes(controller, trip_time(2.0, tms=0.05) + 0.1)
    trips = [m for m in controller.reports() if isinstance(m, SimEvent) and m.kind == "trip"]
    assert [t.mRID for t in trips] == [ALPHA_BETA]
    assert controller.sent.count(("event", ("lines", "Line", "Alpha-Beta 400 kV line", "disconnect", {}))) == 1
    time_passes(controller, 0.02)
    assert len([m for m in controller.reports() if isinstance(m, CimEdits)]) == 1


def test_a_line_with_no_breaker_is_tripped_by_its_terminal(repo):
    controller = controller_of(repo, tms=0.05)
    current = abs(controller.live.current(ALPHA_BETA, end=1))
    controller.limits = {(ALPHA_BETA, 1): current / 2}
    time_passes(controller, 0.0)
    controller.reports()
    time_passes(controller, trip_time(2.0, tms=0.05) + 0.1)
    controller.reports()
    assert ("event", ("lines", "Line", "Alpha-Beta 400 kV line", "disconnect", {})) in controller.sent
    time_passes(controller, 0.02)
    (edits,) = [m for m in controller.reports() if isinstance(m, CimEdits)]
    assert edits.cause == "protection" and edits.edits[0].attribute == "ACDCTerminal.connected"


def test_protection_turned_off_trips_nothing(repo):
    controller = controller_of(repo, enabled=False, tms=0.05)
    current = abs(controller.live.current(ALPHA_GAMMA, end=1))
    controller.limits = {(ALPHA_GAMMA, 1): current / 2}
    time_passes(controller, 0.0)
    time_passes(controller, 60.0)
    assert controller.reports() == [] and controller.sent == []


def test_the_limits_are_the_graph_s_permanent_current_limits(repo):
    # The sample grid has none, so no line is protected against overload there.
    assert controller_of(repo).limits == {}
