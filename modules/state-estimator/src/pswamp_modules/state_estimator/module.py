"""The State Estimator module: ``PmuFrame`` in, a ``StateEstimate`` of the grid out, every ``period`` s.

For now this is a **dummy** estimator. It assumes the PMUs measure what the state needs, and reports
what they measure. It doesn't solve a weighted least-squares problem. Each station's voltage phasor
is read from its PMU, or estimated across a branch from a measured neighbour (``Branch`` with
``estimate=True``, in ``component_models``). Each station's net injection is the sum of its branches'
flows. ``source`` says which of the three a voltage is. A real estimator replaces ``estimate`` and
keeps the message.

The analysis is a plain function, ``estimate``; ``process`` only builds the models when the layout
or the graph changes, picks the frames to publish, and hands each one over. The same module runs
hosted, or from a script::

    module = StateEstimatorModule(period=0)       # every frame
    module.cim_repo = repo                        # a script's own store; hosted, the core connects one
    module.run_one(frame).result                  # a StateEstimate

The result goes on the transport (topic ``StateEstimatorResult``). Nothing is written to the CIM
graph: ``SV.md`` says how the graph's SV profile could follow the estimate.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np

from pswamp_core.modules import Module
from pswamp_models.pmu import PmuFrame, PmuHeader
from pswamp_models.state_estimator import BusEstimate, StateEstimate, StateEstimatorResult

from .component_models import Branch, Bus, pmu_measurements, values_of

__all__ = ["StateEstimatorModule", "estimate"]

_SOURCE = ("measured", "estimated", "missing")


def _number(x: float) -> float | None:
    return float(x) if np.isfinite(x) else None


def estimate(bus: Bus, branch: Branch, meas, cim_reference: str | None = None) -> StateEstimate:
    """The state of the grid in one frame (a ``PmuFrame`` or its values): every station of ``bus``,
    its voltage measured or estimated across ``branch``, and its net injection from the branch flows."""
    values = values_of(meas)
    measured = np.isfinite(bus.V(values))
    V = branch.voltages(values, estimate=True)  # kV, every station of bus.names
    S = branch.net_injection(values, estimate=True)  # MVA into the branches: generation less load
    source = np.where(measured, 0, np.where(np.isfinite(V), 1, 2))
    with np.errstate(invalid="ignore", divide="ignore"):
        magnitude, angle, pu = np.abs(V), np.degrees(np.angle(V)), np.abs(V) / bus.V_n
    buses = [
        BusEstimate(
            mRID=str(bus.mrid[i]),
            station=str(bus.names[i]),
            v_kv=_number(magnitude[i]),
            v_pu=_number(pu[i]),
            angle_deg=_number(angle[i]) if source[i] != 2 else None,
            p_mw=_number(S[i].real),
            q_mvar=_number(S[i].imag),
            source=_SOURCE[source[i]],
        )
        for i in range(len(bus.names))
    ]
    return StateEstimate(
        cimReferenceId=cim_reference,
        measured=int(np.sum(source == 0)),
        estimated=int(np.sum(source == 1)),
        buses=buses,
    )


class StateEstimatorModule(Module):
    name = "state-estimator"
    inputs = (PmuFrame,)
    outputs = (StateEstimatorResult,)
    cim = True  # read the CIM graph through self.cim_repo
    blocking = True  # building the models runs SPARQL queries: keep that off the event loop

    def __init__(self, period: float = 1.0) -> None:
        """``period``: seconds of frame time between two estimates; 0 estimates every frame."""
        super().__init__()
        self.period = period
        self.parameters = {"period": period}
        self._table = None  # the graph's PMU measurements: depends on the graph only
        self._layout: tuple | None = None  # the layout the models below were built for
        self._bus: Bus | None = None
        self._branch: Branch | None = None
        self._last: datetime | None = None  # the frame time of the last estimate

    def reset(self) -> None:
        self._last = None  # the stream starts over: its frame times go back

    def cim_changed(self) -> None:
        # The graph moved (a breaker, a reset): forget everything derived from it.
        self._table = None
        self._layout = None

    def _models_for(self, header: PmuHeader) -> None:
        # Not header_id alone: it hashes neither ``analog`` nor ``cimReferenceId``, so a
        # layout before and after enrichment shares it.
        layout = (header.header_id, header.cimReferenceId, tuple(header.analog or ()))
        if layout == self._layout:
            return
        if self._table is None:
            self._table = pmu_measurements(self.cim_repo)
        self._bus = Bus.from_cim(self.cim_repo, header, measurements=self._table)
        self._branch = Branch.from_cim(self.cim_repo, header, bus=self._bus, measurements=self._table)
        self._layout = layout

    def _due(self, at: datetime) -> bool:
        return self._last is None or (at - self._last).total_seconds() >= self.period or at < self._last

    def process(self, frame: PmuFrame) -> StateEstimate | None:
        if not self._due(frame.timestamp):
            return None
        self._models_for(frame.header)
        result = estimate(self._bus, self._branch, frame, frame.header.cimReferenceId)
        if result.measured == 0:
            return None  # a frame whose columns name no Analog of the graph tells nothing of it
        self._last = frame.timestamp
        return result
