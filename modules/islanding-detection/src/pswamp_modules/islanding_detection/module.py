"""The Islanding detection module: ``PmuFrame`` in, ``IslandingDetectionResult`` out, about once a
second.

Every frame's frequency columns are appended to a ``TimeWindow`` (the last
``window_length_s`` seconds of every station). Every ``1 / eval_freq`` seconds
of *message* time, never wall-clock time, so a replay behaves as the live feed
it recorded, the window goes through ``detect_islands`` (``core.py``), and the
groups of station indexes it returns are reported by station name. Nothing is
published until the window has filled.

Each assessment also sets the module's ``status``: ``Emergency`` when there is
an island, ``OK`` when there is none. An ``AlarmRaiser`` turns that into
``AlarmEvent``s, published beside the result: ``init`` when an emergency
begins, ``not_critical`` once the grid has been whole for ``alarm_hold_s``.

``process`` is plain synchronous code returning the body; the base class wraps
it in ``IslandingDetectionResult``. The same module runs hosted, or from a script::

    for frame in frames:
        for result in module.run(frame):
            result.result.islands

The window and the active alarm are the module's state: ``reset`` drops both
when the stream starts over (a seek, a loop), and a frame with a new channel
layout replaces the window.
"""

import numpy as np

from pswamp_core.alarms import AlarmRaiser
from pswamp_core.modules import Module
from pswamp_models.common import AlarmEvent, AppStatus
from pswamp_models.islanding_detection import IslandingDetectionBody, IslandingDetectionResult
from pswamp_models.pmu import PmuFrame
from pswamp_modules.islanding_detection.core import detect_islands
from pswamp_modules.islanding_detection.time_window import TimeWindow


__all__ = ["IslandingDetectionModule"]

WINDOW_LENGTH_S = 10.0  # seconds of history each evaluation looks at
EVAL_FREQ = 1.0  # evaluations per second of message time
MEAN_THRESHOLD = 0.05  # Hz: RMS distance under which two stations are in one island
ALARM_HOLD_S = 15.0  # seconds without an island before an alarm is no longer critical


class IslandingDetectionModule(Module):
    name = "islanding-detection"
    inputs = (PmuFrame,)
    outputs = (IslandingDetectionResult, AlarmEvent)

    def __init__(
        self,
        window_length_s=WINDOW_LENGTH_S,
        eval_freq=EVAL_FREQ,
        mean_threshold=MEAN_THRESHOLD,
        alarm_hold_s=ALARM_HOLD_S,
    ):
        super().__init__()
        self.window_length_s = window_length_s
        self.eval_freq = eval_freq
        self.mean_threshold = mean_threshold
        self.parameters = {
            "window_length_s": window_length_s,
            "eval_freq": eval_freq,
            "mean_threshold": mean_threshold,
            "alarm_hold_s": alarm_hold_s,
        }
        self.alarms = AlarmRaiser(self.identity, hold_s=alarm_hold_s)
        self.reset()

    def reset(self) -> None:
        self.time_window: TimeWindow | None = None
        self._header_id: str | None = None
        self._columns: list[int] = []
        self._stations: list[str] = []
        self._next_eval: float | None = None
        self.status: AppStatus = "OK"
        self.alarms.reset()

    def _new_window(self, frame: PmuFrame) -> None:
        """A window sized for this frame's layout and rate."""
        header = frame.header
        self._header_id = header.header_id
        self._columns = header.columns(measurement="f")
        self._stations = [header.station[i] for i in self._columns]
        n_samples = max(int(round(self.window_length_s * header.data_rate)), 10)  # the core averages over 10
        self.time_window = TimeWindow(n_samples=n_samples, n_cols=len(self._columns))
        self._next_eval = None

    def process(self, frame: PmuFrame) -> list[IslandingDetectionBody | AlarmEvent | None] | None:
        if frame.header.header_id != self._header_id:
            self._new_window(frame)
        if not self._columns:
            return None  # no frequency channels in this stream

        t = frame.timestamp.timestamp()
        # A missing value, or a zero frequency (a PMU with no lock), is NaN.
        values = np.array([frame.values[i] for i in self._columns], dtype=float)
        values[values == 0] = np.nan
        self.time_window.append(t, values)

        if self._next_eval is not None and t < self._next_eval:
            return None
        self._next_eval = t + 1 / self.eval_freq

        found = detect_islands(*self.time_window.get(), threshold=self.mean_threshold)
        if found is None:
            return None  # the window has not filled yet
        _, islands = found
        self.status = "Emergency" if islands else "OK"
        body = IslandingDetectionBody(
            islands=[[self._stations[i] for i in island] for island in islands], status=self.status
        )
        return [body, self.alarms.update(self.status, frame.timestamp)]
