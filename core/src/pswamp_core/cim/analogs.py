# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The PMU Analogs: one CIM ``Analog`` for every place a PMU can observe the grid.

A grid model rarely carries measurements, so the grid is given them when it is
loaded (``add_pmu_analogs``):

- a voltage (``V``) and a frequency (``F``) per voltage level of each substation,
  at its main busbar: the node of a ``BusbarSection``, else the one with the most
  terminals;
- a current (``I``) at each end of each line.

Each is named by one rule, ``analog_name``: ``PMU_<substation>_<kV>_<V|F|I>``, and
for a current ``_<line>`` after it (``PMU_Beta_400_V``,
``PMU_Beta_400_I_Alpha-Beta_400_kV_line``). That name is how a PMU column finds
its Analog (``analog_index``) and how the simulation knows what to measure
(``analog_table``). A phasor is one Analog: its magnitude and angle columns share
it, and a frequency's ``df`` column shares the frequency's.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal

from lazycim import F, L
from lazycim.sim.topology import terminal_table

if TYPE_CHECKING:
    import pandas as pd
    from lazycim import CIMRepository

__all__ = ["MEASUREMENT_TYPES", "Quantity", "add_pmu_analogs", "analog_index", "analog_name", "analog_table"]

Quantity = Literal["V", "F", "I"]

#: Each quantity's CIM ``Measurement.measurementType``, and back.
MEASUREMENT_TYPES: dict[str, str] = {"V": "LineToLineVoltage", "F": "Frequency", "I": "LineCurrent"}
_QUANTITY = {kind: quantity for quantity, kind in MEASUREMENT_TYPES.items()}


def _part(text: object) -> str:
    return re.sub(r"\s+", "_", str(text).strip())


def analog_name(substation: str, kv: float, quantity: Quantity, branch: str | None = None) -> str:
    """The name of the Analog for ``quantity`` at ``substation``'s ``kv`` level (and, for a
    current, on ``branch``). Whitespace becomes ``_``; kV is written without a trailing ``.0``."""
    name = f"PMU_{_part(substation)}_{float(kv):g}_{quantity}"
    return f"{name}_{_part(branch)}" if branch is not None else name


def _levels(repo: CIMRepository) -> pd.DataFrame:
    """Each connectivity node with its voltage level's substation name and kV."""
    nodes = repo.query(L.ConnectivityNodes).to_dataframe(node=F.mRID, level=F.ConnectivityNodeContainer.mRID)
    levels = repo.query(L.VoltageLevels).to_dataframe(
        level=F.mRID, substation=F.Substation.name, kv=F.BaseVoltage.nominalVoltage
    )
    return nodes.merge(levels, on="level")


def add_pmu_analogs(repo: CIMRepository) -> int:
    """Give the grid in ``repo`` its PMU Analogs (see the module), and return how many.

    Not committed: the caller commits, once. Needs the Operation profile in the
    repository's vocabulary."""
    terminals = terminal_table(repo)
    at = terminals.merge(_levels(repo), on="node")
    busbars = set(repo.query(L.BusbarSections).to_dataframe(mRID=F.mRID).get("mRID", ()))
    lines = repo.query(L.ACLineSegments).to_dataframe(mRID=F.mRID, name=F.name)

    created = 0
    for level, rows in at.groupby("level", sort=True):
        on_busbar = rows[rows["equipment"].isin(busbars)]
        nodes = on_busbar if not on_busbar.empty else rows
        main = nodes["node"].value_counts().sort_index().idxmax()  # the most terminals; ties by mRID
        terminal = rows[rows["node"] == main].sort_values(["terminal"]).iloc[0]
        first = rows.iloc[0]
        for quantity in ("V", "F"):
            _create(repo, analog_name(first.substation, first.kv, quantity), quantity, terminal.terminal, level)
            created += 1
    for line in lines.itertuples():
        for end in at[at["equipment"] == line.mRID].itertuples():
            _create(repo, analog_name(end.substation, end.kv, "I", line.name), "I", end.terminal, line.mRID)
            created += 1
    return created


def _create(repo: CIMRepository, name: str, quantity: Quantity, terminal: str, resource: str) -> None:
    repo.L.Analog(
        name=name,
        measurementType=MEASUREMENT_TYPES[quantity],
        Terminal=repo.from_mRID(terminal),
        PowerSystemResource=repo.from_mRID(resource),
    )


def analog_table(repo: CIMRepository) -> pd.DataFrame:
    """Every PMU Analog: ``mRID``, ``name``, ``quantity`` (V, F or I), its ``terminal``, the
    ``node`` that terminal is at, the ``equipment`` it is on and its end (``sequence``)."""
    analogs = repo.query(L.Analogs).to_dataframe(
        mRID=F.mRID,
        name=F.name,
        kind=F.measurementType,
        terminal=F.Terminal.mRID,
        node=F.Terminal.ConnectivityNode.mRID,
        equipment=F.Terminal.ConductingEquipment.mRID,
        sequence=F.Terminal.sequenceNumber,
    )
    if analogs.empty:
        return analogs.assign(quantity=[])
    analogs = analogs[analogs["name"].astype(str).str.startswith("PMU_")].copy()
    analogs["quantity"] = analogs["kind"].map(_QUANTITY)
    return analogs.drop(columns="kind").sort_values("name").reset_index(drop=True)


def analog_index(repo: CIMRepository) -> dict[str, str]:
    """Every PMU Analog's name to its mRID, in one query."""
    table = repo.query(L.Analogs).to_dataframe(mRID=F.mRID, name=F.name)
    return {str(n): m for n, m in zip(table.get("name", ()), table.get("mRID", ()), strict=True) if str(n).startswith("PMU_")}
