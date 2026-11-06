# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The simulated grid as a PMU stream: one column per PMU measurement of the CIM graph.

The graph says where its PMUs measure (``pswamp_core.cim.measurement_table``: the grid's own
Operation profile, or what the core gave a grid that has none), and the stream measures exactly
that: a station per voltage level of each substation (``Beta_400``) with its voltage's magnitude
(``V_Magnitude`` kV) and angle (``V_Angle`` deg), its frequency (``f`` Hz) and its rate of change
(``df`` Hz/s); the current at a line's or a transformer's end (channel ``I_<branch>``:
``I_Magnitude`` A, ``I_Angle`` deg), at the station of that end; and, where the grid has PMUs that
measure them, the power of a generator or a load (channel ``S_<equipment>``: ``P`` MW, ``Q`` Mvar,
signed as CGMES has it: positive into the equipment, so a generator's is negative). Each column's
header carries its own Analog (``PmuHeader.analog``), so a module goes from a value to the graph in
one call. A bus that is de-energised reads ``0`` kV and no angle or frequency; a part of the grid
the model left out reads ``None``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from pswamp_models.pmu import PmuFrame, PmuHeader

from .engine import Snapshot

__all__ = ["Measured", "PmuLayout", "pmu_frame", "pmu_layout", "pmu_values", "read_measurements"]

#: Below this a bus is de-energised: its angle and frequency mean nothing.
DEAD_PU = 1e-3

#: The kinds of equipment a flow is measured on, as ``measurement_table`` classes them.
BRANCHES = ("ACLineSegment", "PowerTransformer")
INJECTIONS = ("SynchronousMachine", "EnergyConsumer")


@dataclass(frozen=True)
class Measured:
    """One measurement of the graph, and what in the model it measures."""

    mrid: str
    source: str  # PMU or SCADA
    quantity: str  # V, V_angle, F, ROCOF, I, I_angle, P, Q, Pos
    #: The station of its node (``<substation>_<kV>``), and the node.
    station: str | None = None
    node: str | None = None
    #: What it is on: the equipment of its terminal (a switch's position: the switch), its name, its class.
    equipment: str | None = None
    equipment_name: str | None = None
    equipment_class: str | None = None
    #: Its terminal's sequence number.
    end: int = 1
    #: 1, or -1 for a flow measured out of the equipment (``positiveFlowIn`` false).
    sign: float = 1.0


def _str(value) -> str | None:
    return value if isinstance(value, str) else None


def read_measurements(repo) -> list[Measured]:
    """Every PMU and SCADA measurement of the graph, with where it measures: a handful of queries."""
    from pswamp_core.cim import measurement_table

    table = measurement_table(repo)
    measured = []
    for row in table.itertuples():
        if not isinstance(row.quantity, str):
            continue
        on_switch = row.quantity == "Pos"
        equipment = _str(row.equipment) if on_switch else (_str(row.terminal_equipment) or _str(row.equipment))
        same = equipment == row.equipment
        measured.append(
            Measured(
                mrid=row.mRID,
                source=row.source,
                quantity=row.quantity,
                station=_str(row.station),
                node=_str(row.node),
                equipment=equipment,
                equipment_name=_str(row.equipment_name) if same else None,
                equipment_class=_str(row.equipment_class) if same else None,
                end=int(row.sequence) if row.sequence == row.sequence and row.sequence is not None else 1,
                sign=-1.0 if row.positiveFlowIn is False else 1.0,
            )
        )
    return measured


_ORDER = {"V": 0, "V_angle": 1, "F": 2, "ROCOF": 3, "I": 4, "I_angle": 5, "P": 6, "Q": 7}
#: Each PMU quantity's column: channel (``None``: by its equipment), measurement and unit.
_COLUMNS = {
    "V": ("V", "V_Magnitude", "kV"),
    "V_angle": ("V", "V_Angle", "deg"),
    "F": ("f", "f", "Hz"),
    "ROCOF": ("f", "df", "Hz/s"),
    "I": (None, "I_Magnitude", "A"),
    "I_angle": (None, "I_Angle", "deg"),
    "P": (None, "P", "MW"),
    "Q": (None, "Q", "Mvar"),
}


def _streamed(m: Measured) -> bool:
    """Whether a PMU measurement is one the stream carries."""
    if m.source != "PMU" or m.quantity not in _ORDER or m.station is None:
        return False
    if m.quantity in ("I", "I_angle"):
        return m.equipment_class in BRANCHES and m.equipment_name is not None
    if m.quantity in ("P", "Q"):
        return m.equipment_class in INJECTIONS and m.equipment_name is not None
    return True


@dataclass(frozen=True)
class Locator:
    """Where in a model built from the graph each kind of thing is (from a ``SimEngine`` and its ids)."""

    bus: dict[str, int]
    kv: np.ndarray
    #: Branch mRID -> ("line" | "trafo", row, from-bus row, to-bus row).
    branch: dict[str, tuple[str, int, int, int]]
    #: Machine or load mRID -> (row in the machines then the loads, sign of its flow into it).
    injection: dict[str, tuple[int, float]]
    #: Switch mRID -> its row.
    switch: dict[str, int]

    @classmethod
    def of(cls, engine, ids: dict) -> Locator:
        bus = {name: i for i, name in enumerate(engine.bus_names)}
        node_bus = {node: bus[name] for node, name in ids.get("node_to_bus", {}).items() if name in bus}
        branch = {}
        for kind, names, ends, group in (
            ("line", engine.line_names, engine.line_buses, "lines"),
            ("trafo", engine.trafo_names, engine.trafo_buses, "transformers"),
        ):
            row_of = {name: i for i, name in enumerate(names)}
            for name, mrid in ids.get(group, {}).items():
                if name in row_of:
                    i = row_of[name]
                    branch[mrid] = (kind, i, bus.get(ends[i][0], -1), bus.get(ends[i][1], -1))
        injection = {}
        for offset, names, sign, group in (
            (0, engine.gen_names, -1.0, "generators"),  # a machine's power flows out of it
            (len(engine.gen_names), engine.load_names, 1.0, "loads"),
        ):
            row_of = {name: offset + i for i, name in enumerate(names)}
            for name, mrid in ids.get(group, {}).items():
                if name in row_of:
                    injection[mrid] = (row_of[name], sign)
        switch_row = {name: i for i, name in enumerate(engine.switch_names)}
        switch = {mrid: switch_row[name] for name, mrid in ids.get("switches", {}).items() if name in switch_row}
        return cls({node: i for node, i in node_bus.items()}, np.asarray(engine.bus_kv, dtype=float), branch, injection, switch)

    def node(self, m: Measured) -> int:
        return self.bus.get(m.node or "", -1)

    def end(self, m: Measured) -> tuple[str, int, int] | None:
        """A branch end: ("line" | "trafo", row, 1 for its from end or 2 for its to end); ``None`` if
        the model does not have it."""
        found = self.branch.get(m.equipment or "")
        if found is None:
            return None
        kind, row, from_bus, to_bus = found
        at = self.node(m)
        side = 1 if at >= 0 and at == from_bus else 2 if at >= 0 and at == to_bus else m.end
        return kind, row, side


@dataclass(frozen=True)
class PmuLayout:
    """The header, and where each column's value is read from a ``Snapshot``: index arrays per quantity,
    built once, so a frame is a few array operations however many columns it has."""

    header: PmuHeader
    #: Voltage magnitudes and angles, frequencies and their rates of change: the column, the bus
    #: (-1: not in the model); the magnitudes' nominal kV.
    v_at: np.ndarray
    v_bus: np.ndarray
    v_kv: np.ndarray
    a_at: np.ndarray
    a_bus: np.ndarray
    f_at: np.ndarray
    f_bus: np.ndarray
    r_at: np.ndarray
    r_bus: np.ndarray
    #: Currents' magnitudes then angles: the column, the row in the lines then the transformers
    #: (-1: not in the model), the side (1 from, 2 to), and whether it is an angle.
    i_at: np.ndarray
    i_row: np.ndarray
    i_side: np.ndarray
    i_angle: np.ndarray
    #: Powers: the column, the row in the machines' then the loads' arrays, and its sign.
    p_at: np.ndarray
    p_row: np.ndarray
    p_sign: np.ndarray
    q_at: np.ndarray
    q_row: np.ndarray
    q_sign: np.ndarray


def pmu_layout(measurements: list[Measured], engine, ids: dict, rate: float) -> PmuLayout:
    """The stream's layout for the PMU measurements among ``measurements`` over the model ``engine``
    was built from (a ``SimEngine``; ``ids`` is the export's ``sim.ids``), at ``rate`` frames per
    second. What the model lacks is -1, and reads ``None``."""
    at = Locator.of(engine, ids)
    n_lines = len(engine.line_names)
    pmu = sorted(
        (m for m in measurements if _streamed(m)),
        key=lambda m: (
            m.station,
            min(_ORDER[m.quantity], 4) if m.quantity not in ("P", "Q") else 6,
            m.equipment_name or "",
            m.end,
            _ORDER[m.quantity],
        ),
    )
    station, channel, measurement, units, analog = [], [], [], [], []
    node = {q: ([], []) for q in ("V", "V_angle", "F", "ROCOF")}
    kv: list[float] = []
    current = ([], [], [], [])
    power = {"P": ([], [], []), "Q": ([], [], [])}
    for m in pmu:
        column = len(station)
        name, label, unit = _COLUMNS[m.quantity]
        if m.quantity in node:
            bus = at.node(m)
            node[m.quantity][0].append(column)
            node[m.quantity][1].append(bus)
            if m.quantity == "V":
                kv.append(float(at.kv[bus]) if bus >= 0 else 0.0)
        elif m.quantity in ("I", "I_angle"):
            name = f"I_{_part(m.equipment_name)}"
            end = at.end(m)
            row = -1 if end is None else end[1] + (n_lines if end[0] == "trafo" else 0)
            current[0].append(column), current[1].append(row), current[2].append(1 if end is None else end[2])
            current[3].append(m.quantity == "I_angle")
        else:
            name = f"S_{_part(m.equipment_name)}"
            row, sign = at.injection.get(m.equipment or "", (-1, 1.0))
            power[m.quantity][0].append(column), power[m.quantity][1].append(row)
            power[m.quantity][2].append(sign * m.sign)
        station.append(m.station)
        channel.append(name)
        measurement.append(label)
        units.append(unit)
        analog.append(m.mrid)
    header = PmuHeader(
        station=station, channel=channel, measurement=measurement, units=units, data_rate=rate, analog=analog
    )
    ints = lambda values: np.array(values, dtype=int)  # noqa: E731
    floats = lambda values: np.array(values, dtype=float)  # noqa: E731
    return PmuLayout(
        header,
        ints(node["V"][0]), ints(node["V"][1]), floats(kv),
        ints(node["V_angle"][0]), ints(node["V_angle"][1]),
        ints(node["F"][0]), ints(node["F"][1]),
        ints(node["ROCOF"][0]), ints(node["ROCOF"][1]),
        ints(current[0]), ints(current[1]), ints(current[2]), np.array(current[3], dtype=bool),
        ints(power["P"][0]), ints(power["P"][1]), floats(power["P"][2]),
        ints(power["Q"][0]), ints(power["Q"][1]), floats(power["Q"][2]),
    )  # fmt: skip


def _part(text: object) -> str:
    return re.sub(r"\s+", "_", str(text).strip())


def _at(values: np.ndarray, rows: np.ndarray) -> np.ndarray:
    """``values`` at ``rows``, NaN where a row is -1 (or there are no values)."""
    if len(values) == 0:
        return np.full(len(rows), np.nan)
    return np.where(rows >= 0, values[np.maximum(rows, 0)], np.nan)


def pmu_values(layout: PmuLayout, snapshot: Snapshot) -> list[float | None]:
    """The values of one frame of ``snapshot``, in the header's column order (``None`` where unknown)."""
    out = np.full(layout.header.n_columns, np.nan)
    with np.errstate(all="ignore"):
        v_pu = _at(snapshot.v_pu, layout.v_bus)
        out[layout.v_at] = np.where(v_pu > DEAD_PU, v_pu * layout.v_kv, np.where(np.isnan(v_pu), np.nan, 0.0))
        for at, bus, values in (
            (layout.a_at, layout.a_bus, snapshot.angle_deg),
            (layout.f_at, layout.f_bus, snapshot.f_hz),
            (layout.r_at, layout.r_bus, snapshot.rocof_hz_s),
        ):
            live = _at(snapshot.v_pu, bus) > DEAD_PU
            out[at] = np.where(live, _at(values, bus), np.nan)
        if len(layout.i_at):
            ka = np.where(
                layout.i_side == 1,
                _at(np.concatenate([snapshot.i_from_ka, snapshot.t_from_ka]), layout.i_row),
                _at(np.concatenate([snapshot.i_to_ka, snapshot.t_to_ka]), layout.i_row),
            )
            out[layout.i_at] = np.where(layout.i_angle, np.degrees(np.angle(ka)), np.abs(ka) * 1000.0)
        flows = np.concatenate([snapshot.gen_p_mw, snapshot.load_p_mw]), np.concatenate([snapshot.gen_q_mvar, snapshot.load_q_mvar])
        for at, row, sign, values in ((layout.p_at, layout.p_row, layout.p_sign, flows[0]), (layout.q_at, layout.q_row, layout.q_sign, flows[1])):
            out[at] = _at(values, row) * sign
    return [x if math.isfinite(x) else None for x in out.tolist()]


def pmu_frame(layout: PmuLayout, snapshot: Snapshot, timestamp: datetime, mrid: str) -> PmuFrame:
    """One frame of ``snapshot`` at ``timestamp``."""
    return PmuFrame(timestamp=timestamp, mRID=mrid, header=layout.header, values=pmu_values(layout, snapshot))
