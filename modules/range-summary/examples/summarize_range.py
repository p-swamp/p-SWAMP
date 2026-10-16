"""Summarize ranges of a small synthetic recording, with no server.

The range summary module answers ``SummarizeRangeCommand`` by reading its own
sources. Here its ``SourceSet`` holds one history source: ten seconds of
synthetic frames, served by a minimal ``SourceModule`` defined below (a plain
``read`` generator; the host reads it as ``aread``). The script
itself stays synchronous: ``run_command`` runs the module's async handler on a
loop of its own. No server, no transport.

    uv run python modules/range-summary/examples/summarize_range.py
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from pswamp_core.command_routing import CommandRefused
from pswamp_core.sources import SourceModule, SourceSet
from pswamp_core.time_range import TimeRange
from pswamp_models.pmu import PmuFrame, PmuHeader
from pswamp_models.range_summary import SummarizeRangeCommand
from pswamp_modules.range_summary import RangeSummaryModule

RATE_HZ = 20.0
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
HEADER = PmuHeader(station=["A", "B"], channel=["f", "f"], measurement=["f", "f"], units=["Hz", "Hz"], data_rate=RATE_HZ)


def recording(seconds: float = 10.0) -> list[PmuFrame]:
    """A slow ±20 mHz swing around 50 Hz, the second station 1 mHz above the first."""
    frames = []
    for n in range(int(seconds * RATE_HZ)):
        t = n / RATE_HZ
        f = 50.0 + 0.02 * math.sin(2 * math.pi * t / seconds)
        frames.append(PmuFrame(timestamp=T0 + timedelta(seconds=t), mRID="synthetic", header=HEADER, values=[f, f + 0.001]))
    return frames


class InMemoryHistory(SourceModule):
    """A history source holding a list of frames."""

    name = "in-memory-history"
    kind = "history"

    def __init__(self, source: str, frames: list[PmuFrame]) -> None:
        super().__init__(source)
        self.frames = frames

    def coverage(self) -> TimeRange:
        return TimeRange(self.frames[0].timestamp, self.frames[-1].timestamp + timedelta(seconds=1 / RATE_HZ))

    def read(self, start=None, end=None):
        for frame in self.frames:
            if TimeRange(start, end).contains(frame.timestamp):
                yield frame


def main() -> None:
    summary = RangeSummaryModule()
    summary.sources = SourceSet([InMemoryHistory("synthetic", recording())])
    for start, end in ((0.0, 2.5), (2.5, 5.0), (5.0, 7.5), (7.5, 10.0)):
        (answer,) = summary.run_command(SummarizeRangeCommand(source="synthetic", offset_s=start, end_offset_s=end))
        r = answer.result
        print(
            f"[{start:4.1f}, {end:4.1f}) s  {r.frames} frames  "
            f"min {r.min_frequency_hz:.4f}  mean {r.mean_frequency_hz:.4f}  max {r.max_frequency_hz:.4f} Hz"
        )
    try:  # a range outside the recording is refused, as hosted it becomes an ErrorEvent
        summary.run_command(SummarizeRangeCommand(source="synthetic", offset_s=20.0, end_offset_s=21.0))
    except CommandRefused as refused:
        print(f"refused: {refused}")


if __name__ == "__main__":
    main()
