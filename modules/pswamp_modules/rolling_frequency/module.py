"""The Rolling frequency module: the mean frequency over the last five seconds.

It is the worked example of a module with a window (doc/module-cookbook.md,
"Caching and windowed algorithms"): it needs five seconds of frames before it
can answer, so it sets ``warm_up_s``, clears its window in ``reset``, and
lets its results be kept with ``cache_results``.

The analysis is a plain function, ``mean_of``; ``process`` keeps the window
and adapts a frame to it.
"""

from collections import deque
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from pswamp_core.messages import PmuFrame, ResultEnvelope
from pswamp_core.modules import Module

__all__ = ["WINDOW_S", "RollingFrequencyBody", "RollingFrequencyModule", "RollingFrequencyResult", "mean_of"]

#: The window: a result is the mean over this many seconds up to its instant.
WINDOW_S = 5.0


def mean_of(values: list[float | None]) -> float | None:
    """The mean of the values that are there; ``None`` when none is."""
    present = [x for x in values if x is not None]
    return sum(present) / len(present) if present else None


class RollingFrequencyBody(BaseModel):
    mean_hz: float = Field(description="Mean frequency across the stations, over the window.")
    window_s: float = Field(description="The window: seconds up to and including this instant.")
    samples: int = Field(description="Frames in the window.")


class RollingFrequencyResult(ResultEnvelope[RollingFrequencyBody]):
    version: Literal["v1"] = "v1"


class RollingFrequencyModule(Module):
    name = "rolling-frequency"
    input_model = PmuFrame
    output_model = RollingFrequencyResult

    #: How many seconds of unbroken input the analysis needs before its answer
    #: counts. While the module warms up, ``process`` is still called with
    #: every input, so it can fill its window, but what it returns is not
    #: published. The warm-up starts at the module's first input and starts
    #: again after every break (see ``reset``). It is counted in the data's
    #: own time, not on the clock.
    #:
    #: Here: the window. Before five seconds of frames are in, the mean would
    #: be over less than it claims.
    warm_up_s = WINDOW_S

    #: ``True`` lets the server keep this module's results for a recording and
    #: show them again when any client is at the same instant. Setting it is a
    #: promise: the same inputs always give the same result. So a result
    #: depends only on the recording and the instant, never on the client, on
    #: a command, on the clock, on chance, or on anything else outside the
    #: inputs. Nothing checks this promise: a cached result from one run is
    #: shown in place of what another run would have computed.
    #:
    #: Here it holds: a result is a sum over the frames of the window, taken in
    #: their order, and nothing else goes in. An analysis that is not
    #: deterministic (a random start, a result that depends on the clock)
    #: leaves this ``False``.
    cache_results = True

    def __init__(self) -> None:
        super().__init__()
        self.parameters = {"window_s": WINDOW_S}
        #: Each frame's instant and its mean frequency, oldest first.
        self._window: deque[tuple[datetime, float]] = deque()

    def reset(self) -> None:
        """Called when the input stops being continuous: the player moved (a
        seek, a step back, a loop, another source) or a frame went missing.
        Throw away everything built from earlier inputs, the window above all.
        Keep settings. It is not called before the first input, and a module
        never calls it itself.

        Here: the window. It drops samples by age, so after a seek back it
        would keep the later ones for good; and a mean across a gap is not
        the mean over the last five seconds."""
        self._window.clear()

    async def process(self, frame: PmuFrame) -> RollingFrequencyBody | None:
        columns = frame.header.columns(measurement="f")
        now = mean_of([frame.values[i] for i in columns])
        if now is None:
            return None  # no station has a frequency in this frame
        self._window.append((frame.timestamp, now))
        oldest = frame.timestamp - timedelta(seconds=WINDOW_S)
        while self._window[0][0] < oldest:
            self._window.popleft()
        values = [value for _, value in self._window]
        return RollingFrequencyBody(mean_hz=sum(values) / len(values), window_s=WINDOW_S, samples=len(values))
