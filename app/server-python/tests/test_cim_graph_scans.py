"""The CIM graph app keeps the latest SCADA scan in the graph (ADR-017): one update per scan, replacing
the last, in a graph of its own that does not move the version stamp. Over the three-substation
sample grid, in an in-process store."""

from __future__ import annotations

import time

import pytest
from test_cim_graph import SETTINGS, needs_profiles, server  # noqa: F401

from pswamp_core.cim import measurement_table
from pswamp_core.cim.store import MEASUREMENTS_GRAPH
from pswamp_core.util.time import utcnow
from pswamp_models.scada import AnalogReading, DiscreteReading, ScadaScan

CIM = "http://iec.ch/TC57/CIM100#"


@pytest.fixture
def writer(monkeypatch):
    monkeypatch.delenv("PSWAMP_CIM_URL", raising=False)
    from cim_graph.grid import Writer

    writer = Writer(SETTINGS)
    writer.state()
    yield writer
    writer.reset()


def scada(writer, quantity: str) -> list[str]:
    table = measurement_table(writer.repo)
    return sorted(table[(table.source == "SCADA") & (table.quantity == quantity)].mRID)


def scan(analogs: dict[str, float], discretes: dict[str, int] | None = None) -> ScadaScan:
    return ScadaScan(
        timestamp=utcnow(),
        source="rtsim-from-cim",
        sim_time=2.0,
        analogs=[AnalogReading(mRID=m, value=v) for m, v in analogs.items()],
        discretes=[DiscreteReading(mRID=m, value=v) for m, v in (discretes or {}).items()],
    )


def latest(writer) -> dict[str, float]:
    """The values in the graph of latest values, by the mRID of the measurement they are of."""
    found = writer.store.backend.execute(
        f"SELECT ?id ?v WHERE {{ GRAPH <{MEASUREMENTS_GRAPH}> {{ "
        f"?value <{CIM}MeasurementValue.MeasurementValueSource> ?source ; ?of ?m ; <{CIM}AnalogValue.value>|<{CIM}DiscreteValue.value> ?v . "
        f"FILTER(?of IN (<{CIM}AnalogValue.Analog>, <{CIM}DiscreteValue.Discrete>)) }} ?m <{CIM}IdentifiedObject.mRID> ?id }}"
    )["results"]["bindings"]
    return {row["id"]["value"]: float(row["v"]["value"]) for row in found}


@needs_profiles
def test_a_scan_is_written_as_the_latest_values_without_moving_the_stamp(writer):
    p, pos = scada(writer, "P"), scada(writer, "Pos")
    version, scans = writer.store.version(), writer.store.scans()
    assert writer.write_scan(scan({p[0]: -230.5, p[1]: 12.0}, {pos[0]: 1})) == (3, 0)
    assert latest(writer) == {p[0]: -230.5, p[1]: 12.0, pos[0]: 1.0}
    assert writer.store.version() == version and writer.store.scans() == scans + 1


@needs_profiles
def test_each_scan_replaces_the_last(writer):
    p = scada(writer, "P")
    writer.write_scan(scan({p[0]: 1.0, p[1]: 2.0}))
    writer.write_scan(scan({p[0]: 3.0}))
    assert latest(writer) == {p[0]: 3.0}


@needs_profiles
def test_a_value_for_no_scada_measurement_of_the_grid_is_left_out(writer):
    p = scada(writer, "P")
    table = measurement_table(writer.repo)
    pmu = table[table.source == "PMU"].mRID.iloc[0]
    assert writer.write_scan(scan({p[0]: 1.0, "nowhere": 2.0, pmu: 3.0}, {p[1]: 1})) == (1, 3)  # an Analog is no Discrete
    assert latest(writer) == {p[0]: 1.0}


@needs_profiles
def test_a_reset_forgets_the_latest_values(writer):
    writer.write_scan(scan({scada(writer, "P")[0]: 1.0}))
    writer.reset()
    assert latest(writer) == {}


@needs_profiles
def test_what_the_simulation_scans_on_the_transport_is_written(server):  # noqa: F811
    import functools

    from cim_graph.api import SIMULATION, graph
    from shared import transport

    app, source = SIMULATION
    with server.websocket_connect("/api/cim-graph/ws?client_id=311") as ws:
        ws.receive_json()  # the grid is loaded
        writer = graph._writer
        p = scada(writer, "P")[0]
        time.sleep(0.2)  # the app's subscription is received
        server.portal.call(functools.partial(transport().publish, scan({p: 42.0}), app=app, key=f"live.{source}"))
        deadline = time.monotonic() + 10
        while latest(writer) != {p: 42.0} and time.monotonic() < deadline:
            time.sleep(0.05)
    assert latest(writer) == {p: 42.0}
