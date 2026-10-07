# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``LiveSynthetic``: a synthetic live feed.

The sample recording's frames, taken in turn and stamped with the current time,
at the recording's own rate (20 Hz). The line trip in the recording comes round
every three seconds. There is no broker behind it: it is a source whose frames
are stamped *now*, arrive at their own pace, and cannot be sought, paused or
replayed (it is not ``Playable``). ``{SOURCE}_PATH`` (``LIVE_PATH``) names the
file whose rows are cycled; the k8s example mounts one from a ConfigMap.

It is written as ``aread``: the host reads it without a thread. A script uses
the synchronous form, which runs it on a private event loop, so a bound is
needed to stop it::

    start = utcnow()
    for frame in LiveSynthetic().read(end=start + timedelta(seconds=2)):
        ...

Every ``read`` is its own pass over the cycle, paced by the wall clock: two
readers each get the feed, not one another's frames.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

from pswamp_core.settings import EnvSetting
from pswamp_core.sources import SourceModule
from pswamp_core.util.time import utcnow
from pswamp_models.pmu import PmuFrame

from .sample import DEFAULT_PATH, load_sample

__all__ = ["LIVE_STREAM_ID", "LiveSynthetic"]

LIVE_STREAM_ID = "n44-live"


class LiveSynthetic(SourceModule):
    """The sample's frames, re-stamped now, at its data rate."""

    name = "live-synthetic"
    kind = "live"
    outputs = (PmuFrame,)
    env_settings = (
        EnvSetting("PATH", "The sample file whose frames are cycled", default=str(DEFAULT_PATH), kind="path"),
    )

    def __init__(self, source: str | None = None, **settings) -> None:
        super().__init__(source, **settings)
        self.recording = load_sample(Path(self.settings.path))

    async def aread(self, start: datetime | None = None, end: datetime | None = None) -> AsyncIterator[PmuFrame]:
        frames = self.recording.frames
        interval = 1.0 / self.recording.header.data_rate
        anchor, index = time.monotonic(), 0
        while True:
            delay = anchor + (index + 1) * interval - time.monotonic()
            if delay < -interval:  # more than a frame behind: skip, don't burst
                anchor, index = time.monotonic(), 0
                continue
            if end is not None:
                remaining = (end - utcnow()).total_seconds()
                if remaining <= max(delay, 0.0):
                    await asyncio.sleep(max(remaining, 0.0))
                    return
            await asyncio.sleep(max(delay, 0.0))
            now = utcnow()
            if end is not None and now >= end:
                return
            source = frames[index % len(frames)]
            index += 1
            if start is None or now >= start:
                yield PmuFrame(timestamp=now, mRID=LIVE_STREAM_ID, header=source.header, values=list(source.values))
