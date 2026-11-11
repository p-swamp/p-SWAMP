# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The grid's measurements: the ``Analog``s and ``Discrete``s of its Operation profile, PMU and SCADA.

A measurement is p-SWAMP's when a value of it (an ``AnalogValue``, a ``DiscreteValue``) comes from
one of the two ``MeasurementValueSource``s, named ``PMU`` and ``SCADA`` (``SOURCES``). A grid that
brings its own Operation profile brings its measurements, and they are used as they are: their
mRIDs are what a PMU frame's columns and a SCADA scan's values point at (ADR-017). A grid that has
none is given them when it is loaded (``add_measurements``), by the conventions such a profile
follows:

- **PMU**, per voltage level of each substation, at its main node (that of a ``BusbarSection``,
  else the one with the most terminals): the voltage's magnitude and angle (``Vmag``, ``Vang``),
  the frequency (``Freq``) and its rate of change (``ROCOF``); per line end, the current's
  magnitude and angle (``Imag``, ``Iang``). A magnitude and its angle are two Analogs.
- **SCADA**: an active and a reactive power (``P``, ``Q``) at each end of each line and
  transformer and at each generator and load; a voltage (``V``) per voltage level; a ``Discrete``
  (``Pos``, a ``SwitchPosition``: 1 closed, 0 open) per switch.

Each is named ``<PMU|SCADA>_<where>_<what>``: ``<where>`` is the substation (with ``_<kV>`` when it
has more than one voltage level), or the equipment's name, with ``_T<n>`` for a branch's end
(``PMU_Beta_Vmag``, ``PMU_Gamma_400_Freq``, ``PMU_Alpha-Beta_400_kV_line_T1_Imag``,
``SCADA_Beta_load_LB_P``, ``SCADA_Beta_bus_coupler_Pos``); whitespace becomes ``_``, one for one. Each
carries its CGMES ``measurementType``, ``unitSymbol`` and ``unitMultiplier``, ``phases`` and, for a
flow, ``positiveFlowIn`` (into the equipment at its terminal); each has a value object tying it to
its source. Their mRIDs are derived from what they measure, so a grid staged twice gets the same.

``measurement_table`` reads them all, one row per measurement, in a handful of queries: what every
user reads (the simulation, the enricher, the pages).
"""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

import pandas as pd
from lazycim import F, L
from lazycim.sim.topology import terminal_table

if TYPE_CHECKING:
    from lazycim import CIMRepository

__all__ = [
    "COLUMNS",
    "QUANTITIES",
    "SOURCES",
    "add_measurements",
    "has_measurements",
    "measurement_table",
    "name_part",
    "station_name",
]

#: The measurement value sources p-SWAMP reads and writes.
SOURCES = ("PMU", "SCADA")

#: What each kind of measurement is, as ``measurement_table``'s ``quantity`` says: a CGMES
#: ``measurementType``, with a ``PhaseAngle`` told apart by what else is measured where it is.
QUANTITIES = {
    "LineToLineVoltage": "V",
    "Frequency": "F",
    "RateOfChangeOfFrequency": "ROCOF",
    "CurrentMagnitude": "I",
    "ActivePower": "P",
    "ReactivePower": "Q",
    "SwitchPosition": "Pos",
}

#: ``measurement_table``'s columns, in order.
COLUMNS = (
    "mRID", "name", "kind", "source", "measurementType", "quantity", "unit", "unitSymbol", "unitMultiplier",
    "phases", "positiveFlowIn", "terminal", "sequence", "node", "equipment", "equipment_class", "equipment_name",
    "terminal_equipment", "substation", "substation_name", "kv", "station",
)  # fmt: skip

# What each generated measurement is: (suffix, measurementType, unitSymbol, unitMultiplier).
_VMAG = ("Vmag", "LineToLineVoltage", "V", "k")
_VANG = ("Vang", "PhaseAngle", "deg", "none")
_FREQ = ("Freq", "Frequency", "Hz", "none")
_ROCOF = ("ROCOF", "RateOfChangeOfFrequency", "HzPerSec", "none")
_IMAG = ("Imag", "CurrentMagnitude", "A", "none")
_IANG = ("Iang", "PhaseAngle", "deg", "none")
_V = ("V", "LineToLineVoltage", "V", "k")
_P = ("P", "ActivePower", "W", "M")
_Q = ("Q", "ReactivePower", "VAr", "M")
_POS = ("Pos", "SwitchPosition", None, None)

_SYMBOLS = {"VAr": "var", "HzPerSec": "Hz/s"}
_MULTIPLIERS = {"none": "", "k": "k", "M": "M", "G": "G", "m": "m"}

#: Where a generated measurement's mRID is derived from.
_NAMESPACE = uuid.UUID("6f1d6c1e-5a52-4c55-9a3e-7073776d7000")


def name_part(text: object) -> str:
    """``text`` as part of a measurement's name: stripped, each whitespace character an ``_``."""
    return re.sub(r"\s", "_", str(text).strip())


def station_name(substation: object, kv: object) -> str:
    """The station a PMU stream labels a voltage level by: ``<substation>_<kV>`` (``Beta_400``)."""
    return f"{re.sub(r'\s+', '_', str(substation).strip())}_{float(kv):g}"


def _unit(symbol: object, multiplier: object) -> str:
    if not isinstance(symbol, str) or symbol in ("", "none"):
        return ""
    prefix = _MULTIPLIERS.get(multiplier, "") if isinstance(multiplier, str) else ""
    return f"{prefix}{_SYMBOLS.get(symbol, symbol)}"


def _text(value: object) -> str | None:
    """A value the graph gave as text; ``None`` for one it did not give (None, NaN, an empty list)."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return str(value).lower()
    return None


def _frame(table: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """``table`` with ``columns``, even when the query found nothing (and so returned no columns)."""
    return table.reindex(columns=columns) if table.empty else table


def _classes(repo: CIMRepository) -> dict[str, tuple[str, str | None]]:
    """Each equipment's (and container's) mRID to the class a measurement on it is read by, and its name."""
    classes = {}
    for name, table in (
        ("VoltageLevel", L.VoltageLevels),
        ("BusbarSection", L.BusbarSections),
        ("Switch", L.Switches),
        ("EnergyConsumer", L.EnergyConsumers),
        ("SynchronousMachine", L.SynchronousMachines),
        ("PowerTransformer", L.PowerTransformers),
        ("ACLineSegment", L.ACLineSegments),
    ):
        found = _frame(repo.query(table).to_dataframe(mRID=F.mRID, name=F.name), ["mRID", "name"])
        for mrid, text in zip(found["mRID"], found["name"], strict=True):
            classes[mrid] = (name, _text(text))
    return classes


def _levels(repo: CIMRepository) -> pd.DataFrame:
    """Each connectivity node: its voltage level, that level's substation (mRID and name) and kV."""
    nodes = _frame(repo.query(L.ConnectivityNodes).to_dataframe(node=F.mRID, level=F.ConnectivityNodeContainer.mRID), ["node", "level"])
    levels = _frame(
        repo.query(L.VoltageLevels).to_dataframe(
            level=F.mRID, substation=F.Substation.mRID, substation_name=F.Substation.name, kv=F.BaseVoltage.nominalVoltage
        ),
        ["level", "substation", "substation_name", "kv"],
    )
    return nodes.merge(levels, on="level", how="left")


def measurement_table(repo: CIMRepository) -> pd.DataFrame:
    """Every PMU and SCADA measurement of the grid (see the module), one row each, by name:

    ``mRID``, ``name``; ``kind`` (``Analog`` or ``Discrete``); ``source`` (``PMU`` or ``SCADA``);
    ``measurementType`` as the graph has it, and ``quantity``, what it is: ``V`` (a voltage's
    magnitude, kV), ``V_angle``, ``F``, ``ROCOF``, ``I`` (a current's magnitude), ``I_angle``, ``P``,
    ``Q``, ``Pos`` (a switch position), or ``None`` for another type; ``unit`` (``kV``, ``MW``,
    ``Mvar``, ``Hz/s``...) from ``unitSymbol`` and ``unitMultiplier``; ``phases``;
    ``positiveFlowIn`` (``True``, ``False``, ``None``); the ``terminal``, its ``sequence`` number and
    the ``node`` it is at; the ``equipment`` (its ``PowerSystemResource``) and that equipment's
    ``equipment_class`` (``ACLineSegment``, ``PowerTransformer``, ``SynchronousMachine``,
    ``EnergyConsumer``, ``Switch``, ``BusbarSection``, ``VoltageLevel``) and ``equipment_name``, and the
    ``terminal_equipment`` the terminal belongs to; the node's ``substation`` (mRID),
    ``substation_name`` and nominal ``kv``, and its ``station``, ``<substation>_<kV>``."""
    common = dict(
        mRID=F.mRID,
        name=F.name,
        measurementType=F.measurementType,
        terminal=F.Terminal.mRID,
        equipment=F.PowerSystemResource.mRID,
    )
    analogs = repo.query(L.Analogs).to_dataframe(
        **common, unitSymbol=F.unitSymbol, unitMultiplier=F.unitMultiplier, phases=F.phases, positiveFlowIn=F.positiveFlowIn
    )
    discretes = repo.query(L.Discretes).to_dataframe(**common, phases=F.phases)
    own = ["mRID", "name", "measurementType", "terminal", "equipment", "unitSymbol", "unitMultiplier", "phases", "positiveFlowIn"]
    analogs = _frame(analogs, own).assign(kind="Analog")
    discretes = _frame(discretes, own[:5] + ["phases"]).assign(kind="Discrete")
    values = pd.concat(
        [
            _frame(repo.query(L.AnalogValues).to_dataframe(measurement=F.Analog.mRID, source=F.MeasurementValueSource.name), ["measurement", "source"]),
            _frame(repo.query(L.DiscreteValues).to_dataframe(measurement=F.Discrete.mRID, source=F.MeasurementValueSource.name), ["measurement", "source"]),
        ]
    )
    values = values[values["source"].isin(SOURCES)].sort_values("source").drop_duplicates("measurement")
    table = pd.concat([analogs, discretes], ignore_index=True).merge(values, left_on="mRID", right_on="measurement")
    table = table.drop(columns="measurement").drop_duplicates("mRID")
    if table.empty:
        return pd.DataFrame(columns=list(COLUMNS))

    for column in ("terminal", "equipment", "name", "measurementType", "unitSymbol", "unitMultiplier", "phases"):
        table[column] = table[column].map(_text)
    table["positiveFlowIn"] = table["positiveFlowIn"].map(lambda x: x if isinstance(x, bool) else {"true": True, "false": False}.get(x))
    terminals = terminal_table(repo).rename(columns={"equipment": "terminal_equipment"})[["terminal", "terminal_equipment", "node", "sequence"]]
    table = table.merge(terminals, on="terminal", how="left").merge(_levels(repo), on="node", how="left")
    classes = _classes(repo)
    table["equipment_class"] = table["equipment"].map(lambda mrid: classes.get(mrid, (None, None))[0])
    table["equipment_name"] = table["equipment"].map(lambda mrid: classes.get(mrid, (None, None))[1])
    table["unit"] = [_unit(s, m) for s, m in zip(table["unitSymbol"], table["unitMultiplier"], strict=True)]
    table["station"] = [
        station_name(s, kv) if isinstance(s, str) and kv == kv and kv is not None else None
        for s, kv in zip(table["substation_name"], table["kv"], strict=True)
    ]
    table["quantity"] = table["measurementType"].map(QUANTITIES)
    angles = table["measurementType"] == "PhaseAngle"
    currents = set(
        zip(*(table.loc[table["quantity"] == "I", column] for column in ("source", "terminal", "equipment")), strict=True)
    )
    table.loc[angles, "quantity"] = [
        "I_angle" if key in currents else "V_angle"
        for key in zip(*(table.loc[angles, column] for column in ("source", "terminal", "equipment")), strict=True)
    ]
    table["sequence"] = table["sequence"].astype("Int64")
    return table[list(COLUMNS)].sort_values("name").reset_index(drop=True)


def has_measurements(repo: CIMRepository) -> bool:
    """Whether the grid has any PMU or SCADA measurement (see the module)."""
    return not measurement_table(repo).empty


def add_measurements(repo: CIMRepository) -> int:
    """Give the grid in ``repo`` its PMU and SCADA measurements (see the module), and return how many.

    Not committed: the caller commits, once. Needs the Operation profile in the repository's
    vocabulary. Call it only for a grid that has none (``has_measurements``)."""
    terminals = terminal_table(repo)
    at = terminals.merge(_levels(repo), on="node")
    busbars = set(repo.query(L.BusbarSections).to_dataframe(mRID=F.mRID).get("mRID", ()))
    named = lambda table: _frame(repo.query(table).to_dataframe(mRID=F.mRID, name=F.name), ["mRID", "name"])  # noqa: E731
    lines, transformers = named(L.ACLineSegments), named(L.PowerTransformers)
    injections = pd.concat([named(L.SynchronousMachines), named(L.EnergyConsumers)])
    switches = named(L.Switches)
    levels_of = at.groupby("substation")["level"].nunique().to_dict()
    sources = {source: repo.L.MeasurementValueSource(mRID=_mrid("source", source), name=source) for source in SOURCES}

    created = 0

    def create(source: str, where: str, what: tuple, terminal: str, resource: str, *, flow: bool = False) -> None:
        nonlocal created
        suffix, kind, symbol, multiplier = what
        name = f"{source}_{where}_{suffix}"
        mrid = _mrid(source, terminal, resource, suffix)
        if kind == "SwitchPosition":
            measurement = repo.L.Discrete(mRID=mrid, name=name, measurementType=kind)
            value = repo.L.DiscreteValue(mRID=_mrid("value", mrid), Discrete=measurement)
        else:
            fields = dict(unitSymbol=symbol, unitMultiplier=multiplier, phases="ABC")
            if flow:
                fields["positiveFlowIn"] = True
            measurement = repo.L.Analog(mRID=mrid, name=name, measurementType=kind, **fields)
            value = repo.L.AnalogValue(mRID=_mrid("value", mrid), Analog=measurement)
        measurement.Terminal = repo.from_mRID(terminal)
        measurement.PowerSystemResource = repo.from_mRID(resource)
        value.MeasurementValueSource = sources[source]
        created += 1

    for level, rows in at.groupby("level", sort=True):
        on_busbar = rows[rows["equipment"].isin(busbars)]
        nodes = on_busbar if not on_busbar.empty else rows
        main = nodes["node"].value_counts().sort_index().idxmax()  # the most terminals; ties by mRID
        here = rows[rows["node"] == main]
        busbar = here[here["equipment"].isin(busbars)].sort_values("terminal")
        terminal = (busbar if not busbar.empty else here.sort_values("terminal")).iloc[0]
        resource = terminal.equipment if not busbar.empty else level
        first = rows.iloc[0]
        where = name_part(first.substation_name)
        if levels_of.get(first.substation, 1) > 1:
            where = f"{where}_{float(first.kv):g}"
        for what in (_VMAG, _VANG, _FREQ, _ROCOF):
            create("PMU", where, what, terminal.terminal, resource)
        create("SCADA", where, _V, terminal.terminal, resource)

    for table, pmu in ((lines, True), (transformers, False)):
        for branch in table.itertuples():
            for end in terminals[terminals["equipment"] == branch.mRID].sort_values("sequence").itertuples():
                where = f"{name_part(branch.name)}_T{int(end.sequence)}"
                if pmu:
                    create("PMU", where, _IMAG, end.terminal, branch.mRID, flow=True)
                    create("PMU", where, _IANG, end.terminal, branch.mRID, flow=True)
                for what in (_P, _Q):
                    create("SCADA", where, what, end.terminal, branch.mRID, flow=True)

    for equipment in injections.itertuples():
        for end in terminals[terminals["equipment"] == equipment.mRID].sort_values("sequence").itertuples():
            for what in (_P, _Q):
                create("SCADA", name_part(equipment.name), what, end.terminal, equipment.mRID, flow=True)

    for switch in switches.itertuples():
        ends = terminals[terminals["equipment"] == switch.mRID].sort_values("sequence")
        if not ends.empty:
            create("SCADA", name_part(switch.name), _POS, ends.iloc[0].terminal, switch.mRID)
    return created


def _mrid(*parts: object) -> str:
    return str(uuid.uuid5(_NAMESPACE, ":".join(str(part) for part in parts)))
