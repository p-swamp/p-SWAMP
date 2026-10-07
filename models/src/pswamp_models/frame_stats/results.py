# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``FrameStatsResult`` (topic ``frame.stats.result``): the statistics of one frame."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..common.results import ResultEnvelope

__all__ = ["FrameStats", "FrameStatsResult"]


class FrameStats(BaseModel):
    """The statistics of one instant."""

    n_stations: int = Field(description="Stations with a frequency value in this frame.")
    mean_frequency_hz: float | None = Field(description="Mean of the stations' frequencies.")
    min_frequency_hz: float | None
    max_frequency_hz: float | None
    angle_spread_deg: float | None = Field(description="Largest minus smallest voltage angle.")
    mean_voltage_kv: float | None


class FrameStatsResult(ResultEnvelope[FrameStats]):
    version: Literal["v1"] = "v1"
