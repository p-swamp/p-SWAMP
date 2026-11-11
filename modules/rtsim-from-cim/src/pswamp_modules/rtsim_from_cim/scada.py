# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The simulated grid as a SCADA system sees it: every SCADA measurement of the CIM graph, scanned.

The graph says what its SCADA measures (``pswamp_core.cim.measurement_table``, source ``SCADA``),
and a scan reads each of those off the simulation (``Flows``), in the units and with the sign the
measurement declares (ADR-017):

- ``P`` (MW) and ``Q`` (Mvar) at a terminal of a line, a transformer, a machine or a load: the power
  flowing into the equipment there, as CGMES signs it (``positiveFlowIn``; a measurement that says
  ``false`` is the other way round), so a generator's is negative;
- ``V`` (kV): the line-to-line voltage's magnitude at the node;
- ``I`` (A): the current's magnitude at a line's or a transformer's end;
- ``Pos`` (a ``Discrete``): 1 for a switch closed, 0 open.

A measurement of a part of the grid the model left out has no value, and is not in the scan; one of
a part that is de-energised reads what the simulation gives (about 0).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .engine import Flows
from .pmu import BRANCHES, INJECTIONS, Locator, Measured

__all__ = ["ScadaLayout", "scada_layout", "scada_values"]


@dataclass(frozen=True)
class ScadaLayout:
    """Where each SCADA measurement's value is read from ``Flows``: built once per model."""

    #: Voltages: the Analog, the bus, its nominal kV.
    v: tuple[list[str], np.ndarray, np.ndarray]
    #: Flows at a branch end: the Analog, the row (lines then transformers), the side (1 from, 2
    #: to), what (0: P, 1: Q, 2: I), the sign.
    branch: tuple[list[str], np.ndarray, np.ndarray, np.ndarray, np.ndarray]
    #: Flows at a machine or a load: the Analog, the row (machines then loads), what (0: P, 1: Q),
    #: the sign (a machine's power flows out of it).
    injection: tuple[list[str], np.ndarray, np.ndarray, np.ndarray]
    #: Switch positions: the Discrete, the switch's row.
    switch: tuple[list[str], np.ndarray]


_WHAT = {"P": 0, "Q": 1, "I": 2}


def scada_layout(measurements: list[Measured], engine, ids: dict) -> ScadaLayout:
    """The scan's layout for the SCADA measurements among ``measurements`` over the model ``engine``
    was built from (``ids`` is the export's ``sim.ids``). What the model lacks is left out."""
    at = Locator.of(engine, ids)
    n_lines = len(engine.line_names)
    v = ([], [], [])
    branch = ([], [], [], [], [])
    injection = ([], [], [], [])
    switch = ([], [])
    for m in measurements:
        if m.source != "SCADA":
            continue
        if m.quantity == "V":
            bus = at.node(m)
            if bus >= 0:
                v[0].append(m.mrid), v[1].append(bus), v[2].append(float(at.kv[bus]))
        elif m.quantity in _WHAT and m.equipment_class in BRANCHES:
            end = at.end(m)
            if end is not None:
                kind, row, side = end
                branch[0].append(m.mrid), branch[1].append(row + (n_lines if kind == "trafo" else 0))
                branch[2].append(side), branch[3].append(_WHAT[m.quantity]), branch[4].append(m.sign)
        elif m.quantity in ("P", "Q") and m.equipment_class in INJECTIONS:
            found = at.injection.get(m.equipment or "")
            if found is not None:
                row, sign = found
                injection[0].append(m.mrid), injection[1].append(row), injection[2].append(_WHAT[m.quantity])
                injection[3].append(sign * m.sign)
        elif m.quantity == "Pos":
            row = at.switch.get(m.equipment or "")
            if row is not None:
                switch[0].append(m.mrid), switch[1].append(row)
    ints = lambda values: np.array(values, dtype=int)  # noqa: E731
    floats = lambda values: np.array(values, dtype=float)  # noqa: E731
    return ScadaLayout(
        (v[0], ints(v[1]), floats(v[2])),
        (branch[0], ints(branch[1]), ints(branch[2]), ints(branch[3]), floats(branch[4])),
        (injection[0], ints(injection[1]), ints(injection[2]), floats(injection[3])),
        (switch[0], ints(switch[1])),
    )


def scada_values(layout: ScadaLayout, flows: Flows) -> tuple[list[tuple[str, float]], list[tuple[str, int]]]:
    """One scan of ``flows``: each Analog's value and each Discrete's, by mRID (a value that is not a
    finite number is left out)."""
    analogs: list[tuple[str, float]] = []
    with np.errstate(all="ignore"):
        mrids, bus, kv = layout.v
        if mrids:
            analogs += zip(mrids, (flows.v_pu[bus] * kv).tolist(), strict=True)
        mrids, row, side, what, sign = layout.branch
        if mrids:
            s = np.where(side == 1, flows.s_from_mva[row], flows.s_to_mva[row])
            amperes = np.abs(np.where(side == 1, flows.i_from_ka[row], flows.i_to_ka[row])) * 1000.0
            value = np.where(what == 0, s.real * sign, np.where(what == 1, s.imag * sign, amperes))
            analogs += zip(mrids, value.tolist(), strict=True)
        mrids, row, what, sign = layout.injection
        if mrids:
            value = np.where(what == 0, flows.p_mw[row], flows.q_mvar[row]) * sign
            analogs += zip(mrids, value.tolist(), strict=True)
    mrids, row = layout.switch
    discretes = list(zip(mrids, flows.closed[row].astype(int).tolist(), strict=True)) if mrids else []
    return [(mrid, value) for mrid, value in analogs if math.isfinite(value)], discretes
