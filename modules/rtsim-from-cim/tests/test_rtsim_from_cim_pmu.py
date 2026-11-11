"""The simulation as a PMU stream: one column per PMU measurement of the graph, each column carrying
its own Analog, read off a ``Snapshot``."""

from __future__ import annotations

import math

import pytest

from lazycim.sim import get_exporter

from pswamp_core.cim import SAMPLE_GRID, CimSettings, connect_reader, measurement_table
from pswamp_core.util.time import utcnow
from pswamp_modules.rtsim_from_cim.engine import EXPORT, SimEngine
from pswamp_modules.rtsim_from_cim.pmu import Measured, pmu_frame, pmu_layout, read_measurements

SETTINGS = CimSettings(cim_path=SAMPLE_GRID)


@pytest.fixture(scope="module")
def setup():
    repo = connect_reader(SETTINGS)
    sim = get_exporter("tops", repo, **EXPORT).build()
    if measurement_table(repo).empty:
        pytest.skip("the grid has no measurements: the CGMES vocabularies are not available to LazyCIM")
    return repo, sim, SimEngine(sim.model), read_measurements(repo)


def column(frame, station, channel, measurement):
    (i,) = frame.header.columns(station=station, channel=channel, measurement=measurement)
    return frame.values[i]


def test_the_layout_is_the_graph_s_pmu_measurements(setup):
    repo, sim, engine, measured = setup
    layout = pmu_layout(measured, engine, sim.ids, 25.0)
    header = layout.header
    assert sorted(set(header.station)) == ["Alpha_400", "Beta_400", "Gamma_132", "Gamma_400"]
    assert header.n_columns == 4 * 4 + 6 * 2  # V, its angle, f and df per station; a magnitude and an angle per line end
    table = measurement_table(repo)
    assert sorted(header.analog) == sorted(table[table.source == "PMU"].mRID)  # each column its own Analog
    assert header.measurement[:4] == ["V_Magnitude", "V_Angle", "f", "df"]
    assert header.columns(station="Alpha_400", channel="I_Alpha-Beta_400_kV_line") != []
    assert header.data_rate == 25.0


def test_a_frame_reads_the_snapshot_in_physical_units(setup):
    _, sim, engine, measured = setup
    layout = pmu_layout(measured, engine, sim.ids, 25.0)
    frame = pmu_frame(layout, engine.step(10), utcnow(), "s")
    assert 380 < column(frame, "Beta_400", "V", "V_Magnitude") < 420
    assert 120 < column(frame, "Gamma_132", "V", "V_Magnitude") < 140
    assert math.isclose(column(frame, "Alpha_400", "f", "f"), 50.0, abs_tol=0.01)
    assert abs(column(frame, "Alpha_400", "f", "df")) < 0.5  # Hz/s, in the steady state
    assert column(frame, "Alpha_400", "I_Alpha-Beta_400_kV_line", "I_Magnitude") > 10  # amperes
    assert -180 <= column(frame, "Alpha_400", "I_Alpha-Beta_400_kV_line", "I_Angle") <= 180


def test_a_current_is_read_at_the_end_its_terminal_is_at(setup):
    _, sim, engine, measured = setup
    layout = pmu_layout(measured, engine, sim.ids, 25.0)
    frame = pmu_frame(layout, engine.step(10), utcnow(), "s")
    alpha = column(frame, "Alpha_400", "I_Alpha-Beta_400_kV_line", "I_Angle")
    beta = column(frame, "Beta_400", "I_Alpha-Beta_400_kV_line", "I_Angle")
    assert abs(abs(alpha - beta) - 180) < 30  # the current into the line at one end comes out at the other


def test_power_is_streamed_only_where_the_grid_has_pmus_that_measure_it(setup):
    _, sim, engine, measured = setup
    layout = pmu_layout(measured, engine, sim.ids, 25.0)
    assert "P" not in layout.header.measurement  # the sample grid's PMUs measure no power
    load = next(m for m in measured if m.source == "SCADA" and m.quantity == "P" and m.equipment_name == "Beta load LB")
    machine = next(m for m in measured if m.source == "SCADA" and m.quantity == "P" and m.equipment_name == "Alpha GA")
    as_pmu = [Measured(**{**vars(m), "source": "PMU", "mrid": f"pmu-{m.mrid}"}) for m in (load, machine)]
    frame = pmu_frame(pmu_layout(as_pmu, engine, sim.ids, 25.0), engine.step(10), utcnow(), "s")
    assert column(frame, "Beta_400", "S_Beta_load_LB", "P") == pytest.approx(400.0, rel=0.02)
    assert column(frame, "Alpha_400", "S_Alpha_GA", "P") < 0  # a generator's power flows out of it, as CGMES signs it
    assert frame.header.units == ["MW", "MW"]


def test_a_line_cut_off_reads_no_current(setup):
    _, sim, base, measured = setup
    engine = SimEngine(sim.model)
    layout = pmu_layout(measured, engine, sim.ids, 25.0)
    before = column(pmu_frame(layout, engine.step(10), utcnow(), "s"), "Alpha_400", "I_Alpha-Gamma_400_kV_line", "I_Magnitude")
    breaker = {mrid: name for name, mrid in sim.ids["switches"].items()}["3f5e0000-0000-4000-8000-0000000000a1"]
    engine.apply(("event", ("switches", "Switch", breaker, "open", {})))
    after = column(pmu_frame(layout, engine.step(50), utcnow(), "s"), "Alpha_400", "I_Alpha-Gamma_400_kV_line", "I_Magnitude")
    assert after < 0.01 * before  # the bay breaker is at Alpha: nothing flows out there
