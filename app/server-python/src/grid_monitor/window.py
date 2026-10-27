"""The measurement window: the last ``seconds`` of every column of the live grid's frames.

One for the process, written by the live grid's follower (``live.py``) and read by the panels, all
on the event loop: nothing here needs a lock. A frame with a new layout (the simulation rebuilt its
model) starts the window over, and moves ``generation``, which is how a reader knows that the
columns it chose are no longer the same columns.
"""

from __future__ import annotations

import numpy as np

from pswamp_models.pmu import PmuFrame, PmuHeader
from pswamp_web.wire import Channel

#: Short names for the measurements the live simulation carries, for a channel's label.
MEASUREMENT_LABELS = {
    "f": "Frequency",
    "df": "ROCOF",
    "V_Magnitude": "V mag",
    "V_Angle": "V angle",
    "I_Magnitude": "I mag",
    "I_Angle": "I angle",
}


def describe(header: PmuHeader) -> list[Channel]:
    """Every column of ``header``, as the channel picker lists it: a current's label names its branch."""
    channels = []
    for idx, (station, channel, measurement) in enumerate(zip(header.station, header.channel, header.measurement, strict=True)):
        what = MEASUREMENT_LABELS.get(measurement, measurement)
        if channel not in ("V", "f"):
            what = f"{channel} {what.removeprefix('I ')}"
        channels.append(Channel(idx=idx, station=station, channel=channel, measurement=measurement, label=f"{station} {what}"))
    return channels


class MeasurementWindow:
    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self.header: PmuHeader | None = None
        #: Moves with every new layout.
        self.generation = 0
        #: How many frames were appended in this generation, which is how a reader knows how many are new.
        self.appended = 0
        self.channels: list[Channel] = []
        self._t = np.full(0, np.nan)
        self._data = np.full((0, 0), np.nan)
        self._k = 0

    @property
    def n_samples(self) -> int:
        return len(self._t)

    def append(self, frame: PmuFrame) -> None:
        if self.header is None or frame.header.header_id != self.header.header_id:
            self._start(frame.header)
        self._t[self._k] = frame.timestamp.timestamp()
        self._data[self._k] = np.array(frame.values, dtype=float)  # None is NaN
        self._k = (self._k + 1) % len(self._t)
        self.appended += 1

    def _start(self, header: PmuHeader) -> None:
        n = max(int(round(self.seconds * header.data_rate)), 1)
        self.header = header
        self.channels = describe(header)
        self._t = np.full(n, np.nan)
        self._data = np.full((n, header.n_columns), np.nan)
        self._k = 0
        self.appended = 0
        self.generation += 1

    def columns(self, measurement: str) -> list[int]:
        return [] if self.header is None else self.header.columns(measurement=measurement)

    def snapshot(self, columns: list[int]) -> tuple[np.ndarray, np.ndarray]:
        """The window's times and ``columns``, oldest first; NaN where nothing has been appended yet."""
        order = np.roll(np.arange(len(self._t)), -self._k)
        return self._t[order], self._data[np.ix_(order, columns)]

    def recent(self, columns: list[int], seconds: float) -> np.ndarray:
        """The last ``seconds`` of ``columns`` (fewer rows while the window fills)."""
        n = min(max(int(round(seconds * self.header.data_rate)), 1), self.appended, len(self._t)) if self.header else 0
        rows = (self._k - 1 - np.arange(n)) % max(len(self._t), 1)
        return self._data[np.ix_(rows, columns)]

    def latest(self, columns: list[int]) -> tuple[float, np.ndarray]:
        """The newest frame's time and ``columns``; NaN before the first."""
        if not self.appended:
            return float("nan"), np.full(len(columns), np.nan)
        row = (self._k - 1) % len(self._t)
        return float(self._t[row]), self._data[row, columns]
