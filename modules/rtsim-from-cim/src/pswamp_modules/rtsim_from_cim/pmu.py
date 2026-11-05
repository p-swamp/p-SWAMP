# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The simulated grid as a PMU stream: one measurement per PMU Analog of the CIM graph.

The graph says where PMUs can observe the grid (``pswamp_core.cim.analogs``), and the stream
measures exactly that: a station per voltage level of each substation (``Beta_400``), with its
voltage phasor (``V_Magnitude`` kV, ``V_Angle`` deg), its frequency (``f`` Hz), the current of
each line leaving it (channel ``I_<line>``: ``I_Magnitude`` A, ``I_Angle`` deg) and the power of each
generator and load on it (channel ``S_<equipment>``: ``P`` MW, ``Q`` Mvar, each its own Analog). Each column's
header carries the Analog it measures (``PmuHeader.analog``), so a module goes from a value to the
graph in one call. A bus that is de-energised, or a line, a machine or a load the model does not
have, reads ``None``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from lazycim import F, L
from pswamp_core.cim.analogs import _part
from pswamp_models.pmu import PmuFrame, PmuHeader

from .engine import Snapshot

__all__ = ["PmuLayout", "pmu_frame", "pmu_layout", "pmu_values", "read_analogs"]

#: Below this a bus is de-energised: its angle and frequency mean nothing.
DEAD_PU = 1e-3


@dataclass(frozen=True)
class Measured:
    """One Analog, and what in the model it measures."""

    mrid: str
    station: str
    quantity: str  # V, F, I, P or Q
    #: V and F: the connectivity node; I: the line (mRID) and the end (1 or 2).
    node: str | None = None
    line: str | None = None
    line_name: str | None = None
    end: int = 1
    #: P and Q: the machine or load (mRID) and its name.
    equipment: str | None = None
    equipment_name: str | None = None


def read_analogs(repo) -> list[Measured]:
    """Every PMU Analog of the graph, with where it measures, in station order: one query per table."""
    from pswamp_core.cim.analogs import analog_table

    analogs = analog_table(repo)
    levels = repo.query(L.ConnectivityNodes).to_dataframe(
        node=F.mRID,
        substation=F.ConnectivityNodeContainer.Substation.name,
        kv=F.ConnectivityNodeContainer.BaseVoltage.nominalVoltage,
    )
    lines = repo.query(L.ACLineSegments).to_dataframe(line=F.mRID, line_name=F.name)
    names = {
        row.mRID: str(row.name)
        for kind in (L.SynchronousMachines, L.EnergyConsumers)
        for row in repo.query(kind).to_dataframe(mRID=F.mRID, name=F.name).itertuples()
    }
    table = analogs.merge(levels, on="node", how="left").merge(lines, left_on="equipment", right_on="line", how="left")
    order = {"V": 0, "F": 1, "I": 2, "P": 3, "Q": 4}
    measured = [
        Measured(
            mrid=row.mRID,
            station=f"{_part(row.substation)}_{float(row.kv):g}",
            quantity=row.quantity,
            node=row.node,
            line=row.line if row.quantity == "I" else None,
            line_name=str(row.line_name) if row.quantity == "I" else None,
            end=int(row.sequence) if row.quantity == "I" else 1,
            equipment=row.equipment if row.quantity in ("P", "Q") else None,
            equipment_name=names.get(row.equipment) if row.quantity in ("P", "Q") else None,
        )
        for row in table.itertuples()
        if row.quantity in order and isinstance(row.substation, str)
    ]
    # Per station: V, F, the currents by line, then each machine's or load's P and Q together.
    return sorted(
        measured,
        key=lambda m: (m.station, min(order[m.quantity], 3), m.equipment_name or "", order[m.quantity], m.line_name or ""),
    )


@dataclass(frozen=True)
class PmuLayout:
    """The header, and where each column's value is read from a ``Snapshot``: index arrays per quantity,
    built once, so a frame is a few array operations however many columns it has."""

    header: PmuHeader
    #: Voltage phasors: the magnitude's column (the angle's is the next), the bus, its nominal kV.
    v_at: np.ndarray
    v_bus: np.ndarray
    v_kv: np.ndarray
    #: Frequencies: the column, the bus.
    f_at: np.ndarray
    f_bus: np.ndarray
    #: Current phasors: the magnitude's column (the angle's is the next), the line, the end (1 or 2).
    i_at: np.ndarray
    i_line: np.ndarray
    i_end: np.ndarray
    #: Powers: the column, and the row in the machines' arrays then the loads' (``Snapshot.gen_*``
    #: followed by ``load_*``), for P and for Q.
    p_at: np.ndarray
    p_row: np.ndarray
    q_at: np.ndarray
    q_row: np.ndarray


def pmu_layout(analogs: list[Measured], engine, ids: dict, rate: float) -> PmuLayout:
    """The stream's layout for ``analogs`` over the model ``engine`` was built from (a ``SimEngine``: its
    ``bus_names``, ``bus_kv``, ``line_names``, ``gen_names`` and ``load_names``; ``ids`` is the export's
    ``sim.ids``), at ``rate`` frames per second. A bus, a line, a machine or a load the model lacks is -1."""
    bus_row = {name: i for i, name in enumerate(engine.bus_names)}
    line_row = {name: i for i, name in enumerate(engine.line_names)}
    line_of = {mrid: name for name, mrid in ids.get("lines", {}).items()}
    node_bus = ids.get("node_to_bus", {})
    # A machine's or a load's row: the machines first, then the loads, as the snapshot's arrays are joined.
    injection_row = {name: i for i, name in enumerate(engine.gen_names)}
    injection_row |= {name: len(engine.gen_names) + i for i, name in enumerate(engine.load_names)}
    injection_of = {mrid: name for group in ("generators", "loads") for name, mrid in ids.get(group, {}).items()}

    station, channel, measurement, units, analog = [], [], [], [], []
    v, f, i = ([], [], []), ([], []), ([], [], [])
    power = {"P": ([], []), "Q": ([], [])}
    for m in analogs:
        at = len(station)
        if m.quantity in power:
            unit = "MW" if m.quantity == "P" else "Mvar"
            columns, name = [(m.quantity, unit)], f"S_{_part(m.equipment_name)}"
            power[m.quantity][0].append(at)
            power[m.quantity][1].append(injection_row.get(injection_of.get(m.equipment, ""), -1))
        elif m.quantity == "I":
            columns = [("I_Magnitude", "A"), ("I_Angle", "deg")]
            name = f"I_{_part(m.line_name)}"
            i[0].append(at), i[1].append(line_row.get(line_of.get(m.line, ""), -1)), i[2].append(m.end)
        else:
            bus = bus_row.get(node_bus.get(m.node, ""), -1)
            if m.quantity == "V":
                columns, name = [("V_Magnitude", "kV"), ("V_Angle", "deg")], "V"
                v[0].append(at), v[1].append(bus), v[2].append(float(engine.bus_kv[bus]) if bus >= 0 else 0.0)
            else:
                columns, name = [("f", "Hz")], "f"
                f[0].append(at), f[1].append(bus)
        for label, unit in columns:
            station.append(m.station)
            channel.append(name)
            measurement.append(label)
            units.append(unit)
            analog.append(m.mrid)
    header = PmuHeader(
        station=station, channel=channel, measurement=measurement, units=units, data_rate=rate, analog=analog
    )
    ints = lambda values: np.array(values, dtype=int)  # noqa: E731
    return PmuLayout(
        header,
        ints(v[0]), ints(v[1]), np.array(v[2], dtype=float),
        ints(f[0]), ints(f[1]),
        ints(i[0]), ints(i[1]), ints(i[2]),
        ints(power["P"][0]), ints(power["P"][1]), ints(power["Q"][0]), ints(power["Q"][1]),
    )  # fmt: skip


def pmu_values(layout: PmuLayout, snapshot: Snapshot) -> list[float | None]:
    """The values of one frame of ``snapshot``, in the header's column order (``None`` where unknown)."""
    out = np.full(layout.header.n_columns, np.nan)
    with np.errstate(all="ignore"):
        bus, ok = np.maximum(layout.v_bus, 0), layout.v_bus >= 0
        v_pu = np.where(ok, snapshot.v_pu[bus] if len(snapshot.v_pu) else np.nan, np.nan)
        live = v_pu > DEAD_PU
        out[layout.v_at] = np.where(ok, np.where(live, v_pu * layout.v_kv, 0.0), np.nan)
        out[layout.v_at + 1] = np.where(live, snapshot.angle_deg[bus] if len(snapshot.angle_deg) else np.nan, np.nan)
        bus, ok = np.maximum(layout.f_bus, 0), layout.f_bus >= 0
        if len(snapshot.v_pu):
            out[layout.f_at] = np.where(ok & (snapshot.v_pu[bus] > DEAD_PU), snapshot.f_hz[bus], np.nan)
        line, ok = np.maximum(layout.i_line, 0), layout.i_line >= 0
        if len(snapshot.i_from_ka):
            current = np.where(layout.i_end == 1, snapshot.i_from_ka[line], snapshot.i_to_ka[line]) * 1000.0
            out[layout.i_at] = np.where(ok, np.abs(current), np.nan)
            out[layout.i_at + 1] = np.where(ok, np.degrees(np.angle(current)), np.nan)
        for at, row, gen, load in (
            (layout.p_at, layout.p_row, snapshot.gen_p_mw, snapshot.load_p_mw),
            (layout.q_at, layout.q_row, snapshot.gen_q_mvar, snapshot.load_q_mvar),
        ):
            values = np.concatenate([gen, load])
            if len(values):
                out[at] = np.where(row >= 0, values[np.maximum(row, 0)], np.nan)
    return [x if math.isfinite(x) else None for x in out.tolist()]


def pmu_frame(layout: PmuLayout, snapshot: Snapshot, timestamp: datetime, mrid: str) -> PmuFrame:
    """One frame of ``snapshot`` at ``timestamp``."""
    return PmuFrame(timestamp=timestamp, mRID=mrid, header=layout.header, values=pmu_values(layout, snapshot))
