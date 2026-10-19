"""The graph as a TOPS model, stepped by ``SimEngine``: it holds 50 Hz, follows a switch, a load and a
new model, measures every line's current, and a run that goes wrong raises. Over the three-substation
sample grid; Nordic44 when cached."""

from __future__ import annotations

import numpy as np
import pytest
from lazycim.sim import RowChange, SimExportError, get_exporter

from pswamp_core.cim import SAMPLE_GRID, CimSettings, GraphVersion, connect_reader, open_store, stage
from pswamp_modules.rtsim_from_cim.engine import EXPORT, Change, SimEngine
from pswamp_modules.rtsim_from_cim.follow import Follower

SETTINGS = CimSettings(cim_path=SAMPLE_GRID)
BAY_BREAKER, COUPLER = "Alpha-Gamma bay breaker", "Beta bus coupler"
ALPHA_GAMMA, ALPHA_BETA = "Alpha-Gamma 400 kV line", "Alpha-Beta 400 kV line"


@pytest.fixture(scope="module")
def sim():
    return Follower(connect_reader(SETTINGS), GraphVersion(open_store(SETTINGS))).sim


@pytest.fixture
def engine(sim):
    return SimEngine(sim.model, open_switches=sim.ids["open_switches"])


@pytest.fixture(autouse=True)
def names(sim):
    """The switches' row names, which the export may suffix with their mRID."""
    global BAY_BREAKER, COUPLER
    row = {mrid: name for name, mrid in sim.ids["lines"].items()}
    BAY_BREAKER, COUPLER = row["3f5e0000-0000-4000-8000-0000000000a1"], row["3f5e0000-0000-4000-8000-000000000034"]


def relative(snapshot):
    """Angles against the first bus: absolute ones turn with the system frequency's small offset."""
    return snapshot.angle_deg - snapshot.angle_deg[0]


def test_every_switch_is_a_branch_and_every_node_a_bus(engine, sim):
    assert {ALPHA_GAMMA, ALPHA_BETA, BAY_BREAKER, COUPLER} <= set(engine.line_names)
    assert len(engine.bus_names) == len(sim.model["buses"]) - 1 == len(set(sim.ids["node_to_bus"].values()))
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


def test_a_line_s_current_flows_from_end_to_end(engine):
    steady = engine.step(10)
    line = engine.line_names.index(ALPHA_BETA)
    assert abs(steady.i_from_ka[line]) > 0.01
    # what goes in comes out, but for what the line's own capacitance draws
    assert abs(abs(steady.i_from_ka[line]) - abs(steady.i_to_ka[line])) < 0.1 * abs(steady.i_from_ka[line])


def test_a_breaker_opened_cuts_its_line_off_and_closed_brings_it_back_once(engine):
    before = engine.step(100)
    assert engine.apply(Change(opened=frozenset({BAY_BREAKER}))) == [f"{BAY_BREAKER} disconnected"]
    after = engine.step(300)
    assert np.max(np.abs(relative(after) - relative(before))) > 0.1  # the flow went round the other way
    assert abs(after.i_from_ka[engine.line_names.index(ALPHA_GAMMA)]) < 1e-3  # nothing flows on the line
    assert engine.apply(Change(opened=frozenset({BAY_BREAKER}))) == []  # nothing new: nothing done
    assert engine.apply(Change(closed=frozenset({BAY_BREAKER}))) == [f"{BAY_BREAKER} connected"]


def test_a_transformer_taken_out_and_brought_back_is_followed_live(engine):
    # TOPS has no transformer event: the engine takes the transformer's admittance off the network,
    # and puts it back, without building the model again.
    (name,) = engine.transformer_names
    before = engine.step(100)
    assert engine.apply(Change(transformers_out=frozenset({name}))) == [f"transformer {name} disconnected"]
    out = engine.step(300)
    assert engine.builds == 1 and np.isfinite(out.v_pu).all()
    assert np.max(np.abs(out.v_pu - before.v_pu)) > 0.05  # the 132 kV side it fed is cut off
    assert engine.apply(Change(transformers_out=frozenset({name}))) == []  # nothing new: nothing done
    assert engine.apply(Change(transformers_in=frozenset({name}))) == [f"transformer {name} connected"]
    back = engine.step(1000)
    assert engine.builds == 1 and np.allclose(back.v_pu, before.v_pu, atol=0.02)


def test_a_transformer_coming_back_that_the_model_left_out_builds_it_again(engine, sim):
    change = Change(transformers_in=frozenset({"unknown"}), model=sim.model, ids=sim.ids, reason="test", live=True)
    (said,) = engine.apply(change)
    assert "built again" in said and engine.builds == 2


def test_a_bus_coupler_is_followed(engine):
    before = engine.step(100)
    engine.apply(Change(opened=frozenset({COUPLER})))
    after = engine.step(300)
    assert np.max(np.abs(after.v_pu - before.v_pu) + np.abs(relative(after) - relative(before))) > 1e-3


def test_a_load_that_draws_more_slows_the_grid(engine, sim):
    name, mrid, p = next((row[0], sim.ids["loads"][row[0]], row[2]) for row in sim.model["loads"][1:])
    before = engine.step(50)
    (said,) = engine.apply(Change(values=(RowChange("loads", name, mrid, "P", p, p * 1.5),)))
    assert said.startswith(f"load {name}")
    after = engine.step(200)
    assert after.f_hz.mean() < before.f_hz.mean() - 1e-3


def test_what_cannot_be_followed_live_is_said_not_done(engine):
    (said,) = engine.apply(Change(values=(RowChange("generators", "G1", "m", "P", 1.0, 2.0),)))
    assert "not followed live" in said
    (said,) = engine.apply(Change(opened=frozenset({"unknown"})))
    assert "not in the model" in said


def test_a_new_model_starts_over_at_steady_state_and_the_clock_runs_on(engine, sim):
    engine.step(100)
    (said,) = engine.apply(Change(model=sim.model, ids=sim.ids, open_switches=frozenset(), reason="rows were added or removed"))
    assert "starts over" in said
    again = engine.step(10)
    assert again.sim_time_s == pytest.approx(1.1) and np.allclose(again.f_hz, 50.0, atol=1e-3)


def test_a_model_with_an_island_leaves_the_island_out(sim):
    import copy

    island = copy.deepcopy(sim.model)
    island["transformers"] = island["transformers"][:1]  # Gamma's 132 kV side is reached through it alone
    engine = SimEngine(island)
    assert len(engine.bus_names) < len(sim.model["buses"]) - 1  # de-energised, not a singular load flow
    assert np.allclose(engine.step(50).f_hz, 50.0, atol=1e-3)


def test_a_model_that_cannot_be_built_again_leaves_the_simulation_running(engine, sim):
    import copy

    broken = copy.deepcopy(sim.model)
    broken["generators"]["GEN"] = broken["generators"]["GEN"][:1]  # no machine: no load flow
    broken["slack_bus"] = None
    (said,) = engine.apply(Change(model=broken, ids=sim.ids, reason="test"))
    assert "goes on as it was" in said and np.isfinite(engine.step(10).v_pu).all()


def test_two_engines_agree(sim):
    a, b = SimEngine(sim.model), SimEngine(sim.model)
    for engine in (a, b):
        engine.apply(Change(opened=frozenset({BAY_BREAKER})))
    sa, sb = a.step(200), b.step(200)
    assert np.allclose(sa.v_pu, sb.v_pu) and np.allclose(sa.f_hz, sb.f_hz)


def test_a_run_that_goes_wrong_raises(engine):
    engine._solver.y[0] = np.nan  # what a blown-up solver leaves
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
    sim = Follower(connect_reader(CimSettings()), GraphVersion(open_store(CimSettings()))).sim
    engine = SimEngine(sim.model, open_switches=sim.ids["open_switches"])
    steady = engine.step(200)
    live = steady.v_pu > 0.5  # the bay nodes the open switches leave floating read 0
    assert np.allclose(steady.f_hz[live], 50.0, atol=2e-3) and 0.9 < steady.v_pu[live].min() and steady.v_pu.max() < 1.1
    breaker = next(name for name in engine.line_names if name.endswith("_S") and name not in sim.ids["open_switches"])
    engine.apply(Change(opened=frozenset({breaker})))
    after = engine.step(500)
    assert np.isfinite(after.v_pu).all()
