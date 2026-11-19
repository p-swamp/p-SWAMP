"""The Line outage module: ``PmuFrame`` in, ``LineOutageResult`` out, ``eval_freq`` times a second.

The desktop package's ``LineOutageDetectionApp`` (``pswamp.monitoring.line_outage_detection``) as a
module. It keeps the last ``window_s`` seconds of every current magnitude column of the stream
(measurement ``I_Magnitude``, or the recordings' ``i_Magnitude``), and every ``1 / eval_freq``
seconds of *message* time looks at them: a current below ``threshold_a`` amperes over the whole
window carries none, one above it carries some. A current that changed since the last evaluation is
a change (``disconnect`` or ``connect``); every one carrying none now is in ``disconnected``. A
current with no value over the whole window (a branch the stream does not have) keeps its state.

Every evaluation is published, changes or not, so the result also says the module is alive: its
``status`` is ``Alert`` while anything carries no current and ``OK`` otherwise. At the start, and
after ``reset``, every current is taken to be carrying some, so a branch that is out already is a
``disconnect`` at the first evaluation.

``process`` is plain synchronous code returning the body; the base class wraps it in
``LineOutageResult``. The same module runs hosted, or from a script::

    for frame in frames:
        for result in module.run(frame):
            result.result.disconnected
"""

import numpy as np

from pswamp_core.modules import Module
from pswamp_models.line_outage import LineOutageBody, LineOutageChange, LineOutageResult, MeasuredCurrent
from pswamp_models.pmu import PmuFrame

__all__ = ["LineOutageModule"]

#: The current magnitude measurements: the live simulation's, and the recordings'.
CURRENT_MAGNITUDES = ("I_Magnitude", "i_Magnitude")
#: A column's unit, in amperes.
AMPERES = {"A": 1.0, "kA": 1000.0}

WINDOW_S = 0.2  # seconds a current must stay below the threshold (the desktop's 10 samples at 50 Hz)
EVAL_FREQ = 5.0  # evaluations per second of message time
THRESHOLD_A = 1.0  # amperes under which a current is none


class LineOutageModule(Module):
    name = "line-outage"
    inputs = (PmuFrame,)
    outputs = (LineOutageResult,)

    def __init__(self, window_s=WINDOW_S, eval_freq=EVAL_FREQ, threshold_a=THRESHOLD_A):
        super().__init__()
        self.window_s = window_s
        self.eval_freq = eval_freq
        self.threshold_a = threshold_a
        self.parameters = {"window_s": window_s, "eval_freq": eval_freq, "threshold_a": threshold_a}
        self.reset()

    def reset(self) -> None:
        self._header_id: str | None = None
        self._columns: list[int] = []
        self._currents: list[MeasuredCurrent] = []
        self._next_eval: float | None = None

    def _new_layout(self, frame: PmuFrame) -> None:
        """A window and a state sized for this frame's layout."""
        header = frame.header
        self._header_id = header.header_id
        self._columns = [i for i, m in enumerate(header.measurement) if m in CURRENT_MAGNITUDES]
        self._currents = [
            MeasuredCurrent(
                station=header.station[i],
                channel=header.channel[i],
                analog=header.analog[i] if header.analog else None,
            )
            for i in self._columns
        ]
        self._scale = np.array([AMPERES.get(header.units[i], 1.0) for i in self._columns])
        n_samples = max(int(round(self.window_s * header.data_rate)), 1)
        self._window = np.full((n_samples, len(self._columns)), np.nan)
        self._k = 0
        self._filled = 0
        self._connected = np.ones(len(self._columns), dtype=bool)
        self._next_eval = None

    def process(self, frame: PmuFrame) -> LineOutageBody | None:
        if frame.header.header_id != self._header_id:
            self._new_layout(frame)
        if not self._columns:
            return None  # no current channels in this stream

        values = np.array([frame.values[i] for i in self._columns], dtype=float)
        self._window[self._k] = values * self._scale
        self._k = (self._k + 1) % len(self._window)
        self._filled = min(self._filled + 1, len(self._window))

        t = frame.timestamp.timestamp()
        if self._filled < len(self._window) or (self._next_eval is not None and t < self._next_eval):
            return None
        self._next_eval = t + 1 / self.eval_freq

        known = ~np.all(np.isnan(self._window), axis=0)
        with np.errstate(invalid="ignore"):
            none = np.all(self._window < self.threshold_a, axis=0)  # NaN compares False: some current
        connected = np.where(known, ~none, self._connected)
        changes = [
            LineOutageChange(kind=kind, currents=[self._currents[i] for i in np.flatnonzero(which)])
            for kind, which in (("disconnect", self._connected & ~connected), ("connect", ~self._connected & connected))
            if which.any()
        ]
        self._connected = connected
        disconnected = [self._currents[i] for i in np.flatnonzero(~connected)]
        return LineOutageBody(changes=changes, disconnected=disconnected, status="Alert" if disconnected else "OK")
