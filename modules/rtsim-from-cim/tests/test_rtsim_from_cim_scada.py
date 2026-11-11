"""The simulation as SCADA sees it: every SCADA measurement of the graph, read off the simulation in
the units and with the sign its measurement declares."""

from __future__ import annotations

import dataclasses

import pytest
from lazycim.sim import get_exporter

from pswamp_core.cim import SAMPLE_GRID, CimSettings, connect_reader, measurement_table
from pswamp_modules.rtsim_from_cim.engine import EXPORT, SimEngine
from pswamp_modules.rtsim_from_cim.pmu import read_measurements
from pswamp_modules.rtsim_from_cim.scada import scada_layout, scada_values

SETTINGS = CimSettings(cim_path=SAMPLE_GRID)
COUPLER = "3f5e0000-0000-4000-8000-000000000034"


@pytest.fixture(scope="module")
def setup():
    repo = connect_reader(SETTINGS)
    if measurement_table(repo).empty:
        pytest.skip("the grid has no measurements: the CGMES vocabularies are not available to LazyCIM")
    sim = get_exporter("tops", repo, **EXPORT).build()
    return sim, read_measurements(repo), {m.mrid: m for m in read_measurements(repo)}


def scan(engine, measured, sim, steps: int = 10) -> tuple[dict[str, float], dict[str, int]]:
    engine.step(steps)
    analogs, discretes = scada_values(scada_layout(measured, engine, sim.ids), engine.flows())
    return dict(analogs), dict(discretes)


def named(by_mrid, values, source_name: str, quantity: str) -> dict[str, float]:
    """``values`` of the measurements on ``source_name`` (an equipment's name, or a station) measuring ``quantity``."""
    return {
        m.mrid: values[m.mrid]
        for m in by_mrid.values()
        if m.quantity == quantity and source_name in (m.equipment_name, m.station) and m.mrid in values
    }


def test_every_scada_measurement_of_the_sample_grid_has_a_value(setup):
    sim, measured, _ = setup
    analogs, discretes = scan(SimEngine(sim.model), measured, sim)
    scada = [m for m in measured if m.source == "SCADA"]
    assert len(analogs) == sum(m.quantity != "Pos" for m in scada) == 28
    assert discretes and set(discretes.values()) == {1}  # every switch closed
    assert len(discretes) == 2


def test_powers_flow_into_the_equipment_as_cgmes_signs_them(setup):
    sim, measured, by_mrid = setup
    analogs, _ = scan(SimEngine(sim.model), measured, sim)
    (load,) = named(by_mrid, analogs, "Beta load LB", "P").values()
    (machine,) = named(by_mrid, analogs, "Alpha GA", "P").values()
    assert load == pytest.approx(400.0, rel=0.02)  # a load draws: into it
    assert machine < -100  # a generator's power flows out of it
    ends = named(by_mrid, analogs, "Alpha-Beta 400 kV line", "P")
    assert len(ends) == 2 and 0 <= sum(ends.values()) < 0.05 * max(abs(x) for x in ends.values())  # in at one end, out at the other, less the losses


def test_a_voltage_is_line_to_line_in_kilovolts(setup):
    sim, measured, by_mrid = setup
    analogs, _ = scan(SimEngine(sim.model), measured, sim)
    assert 380 < next(iter(named(by_mrid, analogs, "Beta_400", "V").values())) < 420
    assert 120 < next(iter(named(by_mrid, analogs, "Gamma_132", "V").values())) < 140


def test_a_switch_opened_reads_zero(setup):
    sim, measured, by_mrid = setup
    engine = SimEngine(sim.model)
    name = {mrid: name for name, mrid in sim.ids["switches"].items()}[COUPLER]
    engine.apply(("event", ("switches", "Switch", name, "open", {})))
    _, discretes = scan(engine, measured, sim)
    (position,) = (m.mrid for m in measured if m.quantity == "Pos" and m.equipment == COUPLER)
    assert discretes[position] == 0


def test_a_measurement_of_what_the_model_left_out_has_no_value(setup):
    sim, measured, _ = setup
    load = next(m for m in measured if m.source == "SCADA" and m.quantity == "P" and m.equipment_name == "Beta load LB")
    gone = dataclasses.replace(load, mrid="gone", equipment="not-in-the-model")
    analogs, _ = scan(SimEngine(sim.model), [load, gone], sim)
    assert set(analogs) == {load.mrid}


def test_a_flow_measured_out_of_the_equipment_has_the_other_sign(setup):
    sim, measured, _ = setup
    load = next(m for m in measured if m.source == "SCADA" and m.quantity == "P" and m.equipment_name == "Beta load LB")
    out = dataclasses.replace(load, mrid="out", sign=-1.0)
    analogs, _ = scan(SimEngine(sim.model), [load, out], sim)
    assert analogs["out"] == pytest.approx(-analogs[load.mrid])
