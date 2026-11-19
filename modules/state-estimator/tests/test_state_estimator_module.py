"""The State Estimator over the sample grid: frames built from the graph's own PMU Analogs."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from pswamp_core.cim import SAMPLE_GRID, CimSettings, connect_reader
from pswamp_models.pmu import PmuFrame, PmuHeader
from pswamp_models.state_estimator import StateEstimatorResult
from pswamp_modules.state_estimator import StateEstimatorModule
from pswamp_modules.state_estimator.component_models import Branch, Bus, pmu_measurements

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def grid():
    repo = connect_reader(CimSettings(cim_path=SAMPLE_GRID))
    table = pmu_measurements(repo)
    if table.empty:
        pytest.skip("the grid has no measurements: the CGMES vocabularies are not available to LazyCIM")
    header = PmuHeader(
        station=[str(s) for s in table.station],
        channel=[str(q) for q in table.quantity],
        measurement=[str(q) for q in table.quantity],
        units=[str(u) for u in table.unit],
        analog=list(table.mRID),
        data_rate=50.0,
    )
    bus = Bus.from_cim(repo, header, measurements=table)
    branch = Branch.from_cim(repo, header, bus=bus, measurements=table)
    # A consistent state: every station at 1.02 p.u., a few degrees apart, and the currents the
    # branches' own models give for it.
    V = bus.V_n * 1.02 * np.exp(1j * np.radians(np.linspace(0.0, -6.0, len(bus.names))))
    I1, I2 = branch._model_currents(V[branch.bus_row[0]], V[branch.bus_row[1]])
    values = np.full(header.n_columns, np.nan)
    for (m, a), phasor in ((bus.v_columns, V), (branch.i_columns[0], I1), (branch.i_columns[1], I2)):
        ok = (m >= 0) & (a >= 0)
        values[m[ok]], values[a[ok]] = np.abs(phasor[ok]), np.degrees(np.angle(phasor[ok]))
    return repo, header, bus, V, values


def frame(header: PmuHeader, values, at: float = 0.0) -> PmuFrame:
    vals = [None if not math.isfinite(v) else float(v) for v in values]
    return PmuFrame(mRID="test", timestamp=T0 + timedelta(seconds=at), header=header, values=vals)


def module(repo, period: float = 0.0) -> StateEstimatorModule:
    m = StateEstimatorModule(period=period)
    m.cim_repo = repo
    return m


def test_every_station_measured_is_reported_as_measured(grid):
    repo, header, bus, V, values = grid
    result = module(repo).run_one(frame(header, values))
    assert isinstance(result, StateEstimatorResult)
    estimate = result.result
    assert [b.station for b in estimate.buses] == list(bus.names)
    assert estimate.measured == len(bus.names) and estimate.estimated == 0
    for b, v in zip(estimate.buses, V, strict=True):
        assert b.source == "measured"
        assert b.v_pu == pytest.approx(1.02)
        assert b.angle_deg == pytest.approx(math.degrees(np.angle(v)))
        assert b.p_mw is not None and b.q_mvar is not None


def test_a_station_without_its_pmu_is_estimated_from_a_neighbour(grid):
    repo, header, bus, V, values = grid
    gone = values.copy()
    row = len(bus.names) - 1
    gone[bus.v_columns[0][row]] = gone[bus.v_columns[1][row]] = np.nan
    estimate = module(repo).run_one(frame(header, gone)).result
    b = estimate.buses[row]
    assert b.source == "estimated" and estimate.estimated == 1
    assert b.v_kv == pytest.approx(abs(V[row]), rel=1e-6)
    assert b.angle_deg == pytest.approx(math.degrees(np.angle(V[row])), abs=1e-6)


def test_the_injections_balance_the_losses(grid):
    repo, header, _, _, values = grid
    estimate = module(repo).run_one(frame(header, values)).result
    # What the stations inject is what the branches consume: their losses, small against the flows.
    assert sum(b.p_mw for b in estimate.buses) >= -1e-6


def test_one_estimate_per_period_of_frame_time(grid):
    repo, header, _, _, values = grid
    m = module(repo, period=1.0)
    published = [bool(m.run(frame(header, values, at=k * 0.02))) for k in range(101)]  # 2 s at 50 Hz
    assert published.count(True) == 3 and published[0] and published[50] and published[100]
    m.reset()
    assert m.run(frame(header, values, at=0.0))  # the stream started over


def test_a_frame_naming_no_analog_publishes_nothing(grid):
    repo, header, _, _, values = grid
    bare = header.model_copy(update={"analog": None})
    assert module(repo).run(frame(bare, values)) == []
