"""``StateEstimatorResult``: the State Estimator module's result, a ``StateEstimate`` of the grid."""

from typing import Literal

from pydantic import BaseModel, Field

from ..common import ResultEnvelope

__all__ = ["BusEstimate", "StateEstimate", "StateEstimatorResult"]

#: Where a value came from: a PMU measured it, it was estimated from what was measured, or neither.
Source = Literal["measured", "estimated", "missing"]


class BusEstimate(BaseModel):
    """One station (a voltage level of the graph, named as the PMU stream names it,
    ``<substation>_<kV>``). A value nothing tells is null, never a guess."""

    mRID: str = Field(description="The VoltageLevel's mRID.")
    station: str = Field(description="The station's name, as the PMU stream has it: <substation>_<kV>.")
    v_kv: float | None = Field(default=None, description="Voltage magnitude, line-to-line kV.")
    v_pu: float | None = Field(default=None, description="Voltage magnitude, per unit of the nominal voltage.")
    angle_deg: float | None = Field(
        default=None,
        description="Voltage angle, degrees, as the PMUs measure it (against their common time reference, "
        "not against a slack bus).",
    )
    p_mw: float | None = Field(
        default=None,
        description="Net active power the station injects into the branches, MW: its generation less its "
        "load. Null when the flow on any of its branches is unknown.",
    )
    q_mvar: float | None = Field(default=None, description="Net reactive power injected, likewise, Mvar.")
    source: Source = Field(description="Where the voltage came from.")


class StateEstimate(BaseModel):
    """The grid's state at one instant: every station's voltage phasor and net injection. Branch flows
    are left out, because they follow from the voltages and the branch parameters in the graph."""

    cimReferenceId: str | None = Field(default=None, description="The grid the estimate is of: its EQ model's id.")
    measured: int = Field(description="How many stations have a measured voltage.")
    estimated: int = Field(description="How many have an estimated one.")
    buses: list[BusEstimate] = Field(default_factory=list, description="Every station of the graph.")


class StateEstimatorResult(ResultEnvelope[StateEstimate]):
    version: Literal["v1"] = "v1"
