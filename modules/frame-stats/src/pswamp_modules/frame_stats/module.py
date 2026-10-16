# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``FrameStatsModule``: per-frame statistics, read off one topic and published
on another.

It reads ``PmuFrame`` and publishes ``FrameStatsResult`` (topic
``frame.stats.result``; both in ``pswamp_models.frame_stats``). It finds its columns in the frame's own header, and
re-derives them only when ``header_id`` changes, so it needs no setup and runs
the same in the server, a worker or a script::

    FrameStatsModule().run_one(frame).result.mean_frequency_hz
"""

from __future__ import annotations

from pswamp_core.modules import Module
from pswamp_models.frame_stats import FrameStats, FrameStatsResult
from pswamp_models.pmu import PmuFrame, PmuHeader

__all__ = ["FrameStatsModule"]


class FrameStatsModule(Module):
    """Mean, min and max frequency, voltage angle spread, mean voltage."""

    name = "frame-stats"
    inputs = (PmuFrame,)
    outputs = (FrameStatsResult,)

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

    def process(self, frame: PmuFrame) -> FrameStats:
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
