# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The sample file: parsing ``sample_data.txt`` into ``PmuFrame``s.

``sample_data.txt``, beside this file, holds 300 simulated PMU records from the
Nordic 44 simulation: five stations at 20 Hz for three seconds, one line per
station per instant::

    t= 0.050s  PMU=3000  V= 419.95kV  ang=   -0.00deg  f= 49.9999Hz

It is parsed once per path into 60 ``PmuFrame``s sharing one header (per
station: ``V_Magnitude`` kV, ``V_Angle`` deg, ``f`` Hz). The file's relative
``t`` is anchored at ``EPOCH``, so the recording sits at a fixed place on the
time axis.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from pswamp_core.time_range import TimeRange
from pswamp_core.util.time import UTC
from pswamp_models.pmu import PmuFrame, PmuHeader

__all__ = ["DEFAULT_PATH", "EPOCH", "STREAM_ID", "SampleRecording", "load_sample"]

DEFAULT_PATH = Path(__file__).parent / "sample_data.txt"

#: Where the recording's t = 0 sits on the time axis.
EPOCH = datetime(2026, 1, 1, tzinfo=UTC)

#: The mRID every frame carries.
STREAM_ID = "n44-sample"

_LINE = re.compile(
    r"t=\s*(?P<t>[-\d.]+)s\s+PMU=(?P<pmu>\S+)\s+V=\s*(?P<v>[-\d.]+)kV\s+"
    r"ang=\s*(?P<ang>[-\d.]+)deg\s+f=\s*(?P<f>[-\d.]+)Hz"
)
_MEASUREMENTS = ("V_Magnitude", "V_Angle", "f")
_CHANNELS = ("V", "V", "f")
_UNITS = ("kV", "deg", "Hz")


@dataclass(frozen=True)
class SampleRecording:
    """The parsed file: its frames in time order, and the layout they share."""

    header: PmuHeader
    frames: tuple[PmuFrame, ...]

    @property
    def coverage(self) -> TimeRange:
        """``[first frame, last frame + one interval)``."""
        interval = timedelta(seconds=1.0 / self.header.data_rate)
        return TimeRange(self.frames[0].timestamp, self.frames[-1].timestamp + interval)


@lru_cache(maxsize=4)
def load_sample(path: Path = DEFAULT_PATH) -> SampleRecording:
    """Parse a sample file. Cached by path; the frames are never modified."""
    instants: dict[float, dict[str, tuple[float, float, float]]] = {}
    stations: dict[str, None] = {}
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        match = _LINE.match(line.strip())
        if match is None:
            raise ValueError(f"{path}:{number}: not a sample record: {line!r}")
        stations.setdefault(match["pmu"], None)
        instants.setdefault(float(match["t"]), {})[match["pmu"]] = (
            float(match["v"]), float(match["ang"]), float(match["f"]),
        )
    if not instants:
        raise ValueError(f"{path}: no records")
    times = sorted(instants)
    steps = [b - a for a, b in zip(times, times[1:])]
    names = list(stations)
    header = PmuHeader(
        station=[name for name in names for _ in _MEASUREMENTS],
        channel=[c for _ in names for c in _CHANNELS],
        measurement=[m for _ in names for m in _MEASUREMENTS],
        units=[u for _ in names for u in _UNITS],
        data_rate=round(1.0 / statistics.median(steps), 6) if steps else 1.0,
    )
    frames = tuple(
        PmuFrame(
            timestamp=EPOCH + timedelta(seconds=t),
            mRID=STREAM_ID,
            header=header,
            values=[x for name in names for x in instants[t].get(name, (None, None, None))],
        )
        for t in times
    )
    return SampleRecording(header=header, frames=frames)
