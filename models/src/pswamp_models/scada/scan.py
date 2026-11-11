# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``ScadaScan``: one SCADA scan, every value read at the same instant."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..common.data_model import DataModel

__all__ = ["AnalogReading", "DiscreteReading", "ScadaScan"]


class AnalogReading(BaseModel):
    """The value of one ``Analog``, in the units it declares (``unitMultiplier`` and ``unitSymbol``:
    MW, Mvar, kV, A), its sign as CGMES has it (``positiveFlowIn``: a power flowing into the equipment
    at its terminal is positive, so a generator's is negative)."""

    mRID: str = Field(description="The Analog's mRID.")
    value: float = Field(allow_inf_nan=False)


class DiscreteReading(BaseModel):
    """The value of one ``Discrete``: for a ``SwitchPosition``, 1 closed and 0 open."""

    mRID: str = Field(description="The Discrete's mRID.")
    value: int


class ScadaScan(DataModel):
    """One scan: every SCADA measurement that has a value, read at one instant. A measurement left
    out has no value now (the part of the grid it is on is not simulated, say)."""

    version: Literal["v1"] = "v1"
    source: str = Field(description="Who scanned: a SCADA feed, or the live simulation ('rtsim-from-cim').")
    sim_time: float | None = Field(default=None, description="When, on a simulation's clock, s; null from a real feed.")
    cimReferenceId: str | None = Field(default=None, description="The grid the measurements are of: its EQ model's id.")
    analogs: list[AnalogReading] = Field(default_factory=list)
    discretes: list[DiscreteReading] = Field(default_factory=list)
