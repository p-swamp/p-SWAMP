# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``FrameStatsModule``: per-frame statistics, read off one topic and published
on another.

It reads ``PmuFrame`` and publishes ``FrameStatsResult`` (topic
``frame.stats.result``). It finds its columns in the frame's own header, and
re-derives them only when ``header_id`` changes, so it needs no setup and runs
the same in the server or a worker.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from pswamp_core.messages import PmuFrame, PmuHeader, ResultEnvelope
from pswamp_core.modules import Module

__all__ = ["FrameStats", "FrameStatsModule", "FrameStatsResult"]


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


class FrameStatsModule(Module):
    """Mean, min and max frequency, voltage angle spread, mean voltage."""

    name = "frame-stats"
    input_model = PmuFrame
    output_model = FrameStatsResult

    def __init__(self) -> None:
        super().__init__()
        self._header_id: str | None = None
        self._f: list[int] = []
        self._v: list[int] = []
        self._angle: list[int] = []

    def _use(self, header: PmuHeader) -> None:
        self._header_id = header.header_id
        self._f = header.columns(measurement="f")
        self._v = header.columns(measurement="V_Magnitude")
        self._angle = header.columns(measurement="V_Angle")
        self.parameters = {"header_id": header.header_id, "stations": header.stations}

    async def process(self, frame: PmuFrame) -> FrameStats:
        if frame.header.header_id != self._header_id:
            self._use(frame.header)
        values = frame.values
        f = [x for i in self._f if (x := values[i]) is not None]
        v = [x for i in self._v if (x := values[i]) is not None]
        angle = [x for i in self._angle if (x := values[i]) is not None]
        return FrameStats(
            n_stations=len(f),
            mean_frequency_hz=sum(f) / len(f) if f else None,
            min_frequency_hz=min(f) if f else None,
            max_frequency_hz=max(f) if f else None,
            angle_spread_deg=max(angle) - min(angle) if angle else None,
            mean_voltage_kv=sum(v) / len(v) if v else None,
        )
