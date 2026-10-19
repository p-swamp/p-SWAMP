"""The simulation as a PMU stream: one column group per PMU Analog of the graph, each column carrying
its Analog, read off a ``Snapshot``."""

from __future__ import annotations

import math

import pytest

from pswamp_core.cim import SAMPLE_GRID, CimSettings, GraphVersion, analog_table, connect_reader, open_store
from pswamp_core.util.time import utcnow
from pswamp_modules.rtsim_from_cim.engine import Change, SimEngine
from pswamp_modules.rtsim_from_cim.follow import Follower
from pswamp_modules.rtsim_from_cim.pmu import pmu_frame, pmu_layout, read_analogs

SETTINGS = CimSettings(cim_path=SAMPLE_GRID)


@pytest.fixture(scope="module")
def setup():
    repo = connect_reader(SETTINGS)
    follower = Follower(repo, GraphVersion(open_store(SETTINGS)))
    if analog_table(repo).empty:
        pytest.skip("the grid has no PMU Analogs: the CGMES vocabularies are not available to LazyCIM")
    engine = SimEngine(follower.sim.model, open_switches=follower.open_switches)
    return repo, follower.sim, engine, read_analogs(repo)


def column(frame, station, channel, measurement):
    (i,) = frame.header.columns(station=station, channel=channel, measurement=measurement)
    return frame.values[i]


def test_the_layout_is_the_graph_s_pmu_analogs(setup):
    repo, sim, engine, analogs = setup
    layout = pmu_layout(analogs, engine, sim.ids, 25.0)
    header = layout.header
    assert sorted(set(header.station)) == ["Alpha_400", "Beta_400", "Gamma_132", "Gamma_400"]
    assert header.n_columns == 4 * 2 + 4 + 6 * 2  # a phasor per V and per I, a value per F
    table = analog_table(repo)
    assert set(header.analog) == set(table.mRID)  # every Analog, and the phasors' two columns share one
    assert header.columns(station="Alpha_400", channel="I_Alpha-Beta_400_kV_line") != []
    assert header.data_rate == 25.0


def test_a_frame_reads_the_snapshot_in_physical_units(setup):
    _, sim, engine, analogs = setup
    layout = pmu_layout(analogs, engine, sim.ids, 25.0)
    frame = pmu_frame(layout, engine.step(10), utcnow(), "s")
    assert 380 < column(frame, "Beta_400", "V", "V_Magnitude") < 420
    assert 120 < column(frame, "Gamma_132", "V", "V_Magnitude") < 140
    assert math.isclose(column(frame, "Alpha_400", "f", "f"), 50.0, abs_tol=0.01)
    assert column(frame, "Alpha_400", "I_Alpha-Beta_400_kV_line", "I_Magnitude") > 10  # amperes


def test_a_line_cut_off_reads_no_current(setup):
    _, sim, base, analogs = setup
    engine = SimEngine(sim.model, open_switches=sim.ids["open_switches"])
    layout = pmu_layout(analogs, engine, sim.ids, 25.0)
    before = column(pmu_frame(layout, engine.step(10), utcnow(), "s"), "Alpha_400", "I_Alpha-Gamma_400_kV_line", "I_Magnitude")
    breaker = {mrid: name for name, mrid in sim.ids["lines"].items()}["3f5e0000-0000-4000-8000-0000000000a1"]
    engine.apply(Change(opened=frozenset({breaker})))
    after = column(pmu_frame(layout, engine.step(50), utcnow(), "s"), "Alpha_400", "I_Alpha-Gamma_400_kV_line", "I_Magnitude")
    assert after < 0.01 * before  # the bay breaker is at Alpha: nothing flows out there
