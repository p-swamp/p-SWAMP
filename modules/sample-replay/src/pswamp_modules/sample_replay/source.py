# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``SampleReplay``: the sample recording as a replayable history source.

Written as a deployment's own source would be: it imports ``pswamp_core`` and
``pswamp_models`` and nothing else. ``read`` is plain synchronous code, so a
script needs no event loop::

    for frame in SampleReplay().read():
        ...

and the host replays it paced, seekable and looping, because it is
``Playable``. ``{SOURCE}_PATH`` (``SAMPLE_PATH``) or ``SampleReplay(path=...)``
picks another file in the same format.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from pswamp_core.time_range import TimeRange
from pswamp_core.playable import Playable
from pswamp_core.settings import EnvSetting
from pswamp_core.sources import SourceModule
from pswamp_models.pmu import PmuFrame

from .sample import DEFAULT_PATH, load_sample

__all__ = ["SampleReplay"]


class SampleReplay(Playable, SourceModule):
    """The sample file as a history: ``coverage`` is its span, ``read`` its frames."""

    name = "sample-replay"
    kind = "history"
    outputs = (PmuFrame,)
    env_settings = (
        EnvSetting("PATH", "The sample file to serve", default=str(DEFAULT_PATH), kind="path"),
    )

    def __init__(self, source: str | None = None, **settings) -> None:
        super().__init__(source, **settings)
        self.recording = load_sample(Path(self.settings.path))

    def coverage(self) -> TimeRange:
        return self.recording.coverage

    def read(self, start: datetime | None = None, end: datetime | None = None) -> Iterator[PmuFrame]:
        window = TimeRange(start, end)
        for frame in self.recording.frames:
            if window.end is not None and frame.timestamp >= window.end:
                return
            if window.contains(frame.timestamp):
                yield frame
