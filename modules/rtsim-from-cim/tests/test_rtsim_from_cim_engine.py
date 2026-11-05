"""The TOPS system the engine's process steps: built from the model LazyCIM exported, it holds 50 Hz,
takes the events and inputs it is sent (a switch, a transformer, a load, a controller's bias), measures
every line's current, starts over from a new model with the clock running on, and raises when a run
goes wrong. Over the three-substation sample grid; Nordic44 when cached."""

from __future__ import annotations

import numpy as np
import pytest
from lazycim.sim import SimExportError, get_exporter

from pswamp_core.cim import SAMPLE_GRID, CimSettings, connect_reader, stage
from pswamp_modules.rtsim_from_cim.engine import EXPORT, SimEngine

SETTINGS = CimSettings(cim_path=SAMPLE_GRID)
BAY_BREAKER, COUPLER = "Alpha-Gamma bay breaker", "Beta bus coupler"
ALPHA_GAMMA, ALPHA_BETA = "Alpha-Gamma 400 kV line", "Alpha-Beta 400 kV line"


@pytest.fixture(scope="module")
def sim():
    return get_exporter("tops", connect_reader(SETTINGS), **EXPORT).build()


@pytest.fixture
def engine(sim):
    return SimEngine(sim.model, dt=0.01)


def relative(snapshot):
    """Angles against the first bus: absolute ones turn with the system frequency's small offset."""
    return snapshot.angle_deg - snapshot.angle_deg[0]


def switch(name: str, action: str) -> tuple:
    return ("event", ("switches", "Switch", name, action, {}))


def test_every_node_is_a_bus_and_every_switch_a_switch_of_tops(engine, sim):
    assert {ALPHA_GAMMA, ALPHA_BETA} <= set(engine.line_names)
    assert {BAY_BREAKER, COUPLER} <= set(sim.ids["switches"])
    assert len(engine.bus_names) == len(sim.model["buses"]) - 1
    assert len(sim.model["pll"]["PLL1"]) - 1 == len(engine.bus_names)  # a PLL on every bus


def test_it_starts_in_the_steady_state_the_model_describes(engine):
    start = engine.snapshot()
    assert start.sim_time_s == 0.0
    settled = engine.step(100)
    assert settled.sim_time_s == pytest.approx(1.0)
    assert np.allclose(settled.f_hz, 50.0, atol=1e-3) and np.all((settled.v_pu > 0.95) & (settled.v_pu < 1.05))
    assert np.allclose(settled.v_pu, start.v_pu, atol=2e-3)  # no disturbance of its own


def test_a_snapshot_is_a_copy(engine):
    first = engine.snapshot()
    before = first.v_pu.copy()
    engine.step(50)
    assert np.array_equal(first.v_pu, before)
    with pytest.raises(AttributeError):
        first.sim_time_s = 1.0  # frozen


def test_its_state_is_what_a_shadow_of_it_reads_from(engine):
    engine.step(10)
    t, y, v = engine.state()
    assert t == pytest.approx(0.1) and y.shape == engine._sim.sol.y.shape and v.shape == engine._sim.sol.v.shape
    y[:] = np.nan  # a copy: the simulation is untouched
    assert np.isfinite(engine.step(1).v_pu).all()


def test_a_line_s_current_flows_from_end_to_end(engine):
    steady = engine.step(10)
    line = engine.line_names.index(ALPHA_BETA)
    assert abs(steady.i_from_ka[line]) > 0.01
    # what goes in comes out, but for what the line's own capacitance draws
    assert abs(abs(steady.i_from_ka[line]) - abs(steady.i_to_ka[line])) < 0.1 * abs(steady.i_from_ka[line])


def test_a_breaker_opened_cuts_its_line_off_and_closed_brings_it_back(engine):
    before = engine.step(100)
    engine.apply(switch(BAY_BREAKER, "open"))
    after = engine.step(300)
    assert np.max(np.abs(relative(after) - relative(before))) > 0.1  # the flow went round the other way
    assert abs(after.i_from_ka[engine.line_names.index(ALPHA_GAMMA)]) < 1e-3  # nothing flows on the line
    engine.apply(switch(BAY_BREAKER, "close"))
    back = engine.step(1000)
    assert abs(back.i_from_ka[engine.line_names.index(ALPHA_GAMMA)]) > 0.01


def test_a_transformer_taken_out_and_brought_back_is_followed_live(engine, sim):
    (name,) = sim.ids["transformers"]
    before = engine.step(100)
    engine.apply(("event", ("trafos", "Trafo", name, "disconnect", {})))
    out = engine.step(300)
    assert engine.builds == 1 and np.isfinite(out.v_pu).all()
    assert np.max(np.abs(out.v_pu - before.v_pu)) > 0.05  # the 132 kV side it fed is cut off
    engine.apply(("event", ("trafos", "Trafo", name, "connect", {})))
    back = engine.step(1000)
    assert engine.builds == 1 and np.allclose(back.v_pu, before.v_pu, atol=0.02)


def test_a_bus_coupler_is_followed(engine):
    before = engine.step(100)
    engine.apply(switch(COUPLER, "open"))
    after = engine.step(300)
    assert np.max(np.abs(after.v_pu - before.v_pu) + np.abs(relative(after) - relative(before))) > 1e-3


def test_each_machine_s_and_each_load_s_power_is_measured(engine, sim):
    snapshot = engine.step(10)
    drawn = dict(zip(engine.load_names, snapshot.load_p_mw, strict=True))
    for row in sim.model["loads"][1:]:  # at steady state, what the model says it draws
        assert drawn[row[0]] == pytest.approx(row[2], rel=0.02)
    assert len(snapshot.load_q_mvar) == len(engine.load_names)
    assert len(snapshot.gen_p_mw) == len(snapshot.gen_q_mvar) == len(engine.gen_names) > 0
    assert snapshot.gen_p_mw.sum() == pytest.approx(snapshot.load_p_mw.sum(), rel=0.05)  # and the losses


def test_a_load_that_draws_more_slows_the_grid(engine, sim):
    name, p = next((row[0], row[2]) for row in sim.model["loads"][1:])
    before = engine.step(50)
    engine.apply(("event", ("loads", "Load", name, "set_power", {"P": p * 1.5})))
    after = engine.step(200)
    assert after.f_hz.mean() < before.f_hz.mean() - 1e-3


def test_an_input_set_on_a_model_reaches_it(engine, sim):
    # What LazyCIM sets for a machine's power when it has no governor: its mechanical power.
    gen = engine._ps.gen["GEN"]
    p_m = float(gen.P_m(engine._ps.x0, engine._ps.v0)[0])
    before = engine.step(50)
    engine.apply(("input", ("gen", "GEN", "P_m", p_m * 0.8, 0)))
    after = engine.step(200)
    assert after.f_hz.mean() < before.f_hz.mean() - 1e-3


def test_messages_for_later_are_due_at_their_time_on_the_build_s_clock(engine, sim):
    later = [switch(BAY_BREAKER, "open")]
    engine.apply(("at", 0.05, later))
    engine.step(4)
    assert engine.due() == []  # 0.04 s
    engine.step(1)
    assert engine.due() == later and engine.due() == []  # once
    engine.apply(("at", 1.0, later))
    engine.rebuild(sim.model)
    engine.step(200)
    assert engine.due() == []  # a model built again forgets what was for later


def test_an_event_that_does_not_apply_raises_and_changes_nothing(engine):
    with pytest.raises(KeyError):
        engine.apply(switch("unknown", "open"))
    with pytest.raises(ValueError):
        engine.apply(("event", ("switches", "Switch", BAY_BREAKER, "explode", {})))
    with pytest.raises(ValueError, match="what to do"):
        engine.apply(("teleport", ()))
    assert np.allclose(engine.step(50).f_hz, 50.0, atol=1e-3)


def test_a_new_model_starts_over_at_steady_state_and_the_clock_runs_on(engine, sim):
    engine.step(100)
    engine.rebuild(sim.model)
    assert engine.builds == 2
    again = engine.step(10)
    assert again.sim_time_s == pytest.approx(1.1) and np.allclose(again.f_hz, 50.0, atol=1e-3)
    assert engine.state()[0] == pytest.approx(0.1)  # its own clock, the build's, starts over


def test_two_engines_agree(sim):
    a, b = SimEngine(sim.model), SimEngine(sim.model)
    for engine in (a, b):
        engine.apply(switch(BAY_BREAKER, "open"))
    sa, sb = a.step(200), b.step(200)
    assert np.allclose(sa.v_pu, sb.v_pu) and np.allclose(sa.f_hz, sb.f_hz)


def test_a_run_that_goes_wrong_raises(engine):
    engine._sim.sol.y[0] = np.nan  # what a blown-up solver leaves
    with pytest.raises(ArithmeticError, match="finite"):
        engine.step(1)


def test_a_grid_the_exporter_refuses_says_why(tmp_path):
    folder = tmp_path / "grid"
    folder.mkdir()
    for file in SAMPLE_GRID.glob("*.xml"):
        # no machine has a voltage target to regulate to: the export names them
        folder.joinpath(file.name).write_text(
            file.read_text(encoding="utf-8").replace("RegulatingControl.targetValue", "RegulatingControl.discrete"),
            encoding="utf-8",
        )
    with pytest.raises(SimExportError, match="voltage target"):
        get_exporter("tops", connect_reader(CimSettings(cim_path=folder)), **EXPORT).build()


def test_nordic44_holds_fifty_hertz_and_follows_a_breaker(monkeypatch):
    monkeypatch.setenv("LAZYCIM_DOWNLOAD", "0")
    try:
        if not stage(CimSettings()).writable:
            pytest.skip("the CGMES vocabularies are not in LazyCIM's cache")
    except RuntimeError as error:
        pytest.skip(f"Nordic44 is not in LazyCIM's cache: {error}")
    sim = get_exporter("tops", connect_reader(CimSettings()), **EXPORT).build()
    engine = SimEngine(sim.model)
    steady = engine.step(200)
    live = steady.v_pu > 0.5
    assert np.allclose(steady.f_hz[live], 50.0, atol=2e-3) and 0.9 < steady.v_pu[live].min() and steady.v_pu.max() < 1.1
    header, *rows = sim.model["switches"]["Switch"]
    closed = header.index("closed")
    breaker = next(row[0] for row in rows if row[closed])
    engine.apply(switch(breaker, "open"))
    after = engine.step(500)
    assert np.isfinite(after.v_pu).all()
