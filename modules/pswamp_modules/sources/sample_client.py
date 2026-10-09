# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``SampleRecordingClient``: the sample recording as a history data client.

Written as a deployment's own provider would be: it imports ``pswamp_core``
and nothing else.

``sample_data.txt``, beside this file, holds 300 simulated PMU records from the Nordic 44
simulation: five stations at 20 Hz for three seconds, one line per station per
instant::

    t= 0.050s  PMU=3000  V= 419.95kV  ang=   -0.00deg  f= 49.9999Hz

It is parsed once, on first use, into 60 ``PmuFrame``s sharing one header
(per station: ``V_Magnitude`` kV, ``V_Angle`` deg, ``f`` Hz). The file's
relative ``t`` is anchored at ``EPOCH``, so the recording sits at a fixed place
on the time axis.

``LineTripRecordingClient`` serves a longer recording in the same format,
``line_trip_30s.txt``: the same five stations for 30 s at 10 Hz, 1500 lines.
Three seconds is too short for an analysis that needs a window of several
seconds; this one has room for it, and something to see: a line trip 5 s in
that islands station 6500, and the reconnection 25 s in.

It was extracted once, by hand, from the grid monitor's recording
(``app/server-python/src/pswamp_web/data/n44_line_trip_50hz.npz``, "Nordic 44
TOPS simulation, p-SWAMP 0ed9d05, recorded 2026-08-18"): 300 samples, every
fifth from the one stamped 15.01 s there, volts as kV and radians as degrees.
The instants are numbered on an even 0.1 s grid from 0, by sample count; the
source's own stamps slip by 10 ms twice in that span. Nothing regenerates it.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import ClassVar

from pswamp_core.datagateway import DataClient, TimeRange
from pswamp_core.messages import PmuFrame, PmuHeader
from pswamp_core.settings import EnvSetting
from pswamp_core.util.time import UTC

__all__ = [
    "DEFAULT_PATH",
    "EPOCH",
    "LINE_TRIP_PATH",
    "LINE_TRIP_STREAM_ID",
    "STREAM_ID",
    "LineTripRecordingClient",
    "SampleRecording",
    "SampleRecordingClient",
    "load_sample",
]

DEFAULT_PATH = Path(__file__).parent / "sample_data.txt"
LINE_TRIP_PATH = Path(__file__).parent / "line_trip_30s.txt"

#: Where the recording's t = 0 sits on the time axis.
EPOCH = datetime(2026, 1, 1, tzinfo=UTC)

#: The mRID every frame of the sample carries.
STREAM_ID = "n44-sample"

#: The mRID every frame of the line-trip recording carries.
LINE_TRIP_STREAM_ID = "n44-line-trip"

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
def load_sample(path: Path = DEFAULT_PATH, mrid: str = STREAM_ID) -> SampleRecording:
    """Parse a sample file into frames carrying ``mrid``. Cached by path and
    mRID; the frames are never modified."""
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
            mRID=mrid,
            header=header,
            values=[x for name in names for x in instants[t].get(name, (None, None, None))],
        )
        for t in times
    )
    return SampleRecording(header=header, frames=frames)


class SampleRecordingClient(DataClient):
    """The sample file as a history. ``{NAME}_PATH`` picks another file."""

    kind = "history"
    env_settings = (
        EnvSetting("PATH", "The sample file to serve", default=str(DEFAULT_PATH), kind="path"),
    )
    #: The mRID its frames carry.
    stream_id: ClassVar[str] = STREAM_ID

    def __init__(self, name: str = "sample", path: Path | str = DEFAULT_PATH) -> None:
        super().__init__(name)
        self.recording = load_sample(Path(path), self.stream_id)

    async def coverage(self) -> TimeRange:
        return self.recording.coverage

    async def consume(self, time_range: TimeRange) -> AsyncIterator[PmuFrame]:
        for record in self.recording.frames:
            if time_range.end is not None and record.timestamp >= time_range.end:
                return
            if time_range.contains(record.timestamp):
                yield record


class LineTripRecordingClient(SampleRecordingClient):
    """The 30 s line-trip recording as a history. ``{NAME}_PATH`` picks another file."""

    env_settings = (
        EnvSetting("PATH", "The recording file to serve", default=str(LINE_TRIP_PATH), kind="path"),
    )
    stream_id = LINE_TRIP_STREAM_ID

    def __init__(self, name: str = "line-trip", path: Path | str = LINE_TRIP_PATH) -> None:
        super().__init__(name, path)
