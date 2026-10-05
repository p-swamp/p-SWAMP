# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``LiveSyntheticClient``: a synthetic live feed.

The sample recording's frames, taken in turn and stamped with the current
time, at the recording's own rate (20 Hz). The line trip in the recording comes
round every three seconds. There is no broker behind it: it is a source whose
frames are stamped *now*, arrive at their own pace, and cannot be sought,
paused or replayed. ``{NAME}_PATH`` names the file whose rows are cycled; the
k8s example mounts one from a ConfigMap.

One ticker per client, started by ``open`` and stopped by ``close``; every
open ``consume`` gets each frame it ticks.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path

from pswamp_core.datagateway import DataClient, TimeRange
from pswamp_core.messages import PmuFrame
from pswamp_core.settings import EnvSetting
from pswamp_core.util.tasks import cancel_and_wait
from pswamp_core.util.time import utcnow

from .sample_client import DEFAULT_PATH, load_sample

__all__ = ["LIVE_STREAM_ID", "LiveSyntheticClient"]

LIVE_STREAM_ID = "n44-live"


class LiveSyntheticClient(DataClient):
    """The sample's frames, re-stamped now, at its data rate."""

    kind = "live"
    env_settings = (
        EnvSetting("PATH", "The sample file whose frames are cycled", default=str(DEFAULT_PATH), kind="path"),
    )

    def __init__(self, name: str = "live", path: Path | str = DEFAULT_PATH) -> None:
        super().__init__(name)
        self.recording = load_sample(Path(path))
        self._tails: list[asyncio.Queue[PmuFrame]] = []
        self._task: asyncio.Task | None = None

    async def open(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._tick(), name=f"{self.name}.tick")

    async def close(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            await cancel_and_wait(task)

    async def _tick(self) -> None:
        frames = self.recording.frames
        interval = 1.0 / self.recording.header.data_rate
        anchor, index = time.monotonic(), 0
        while True:
            delay = anchor + (index + 1) * interval - time.monotonic()
            if delay < -interval:  # more than a frame behind: skip, don't burst
                anchor, index = time.monotonic(), 0
                continue
            await asyncio.sleep(max(delay, 0.0))
            if self._tails:
                source = frames[index % len(frames)]
                frame = PmuFrame(timestamp=utcnow(), mRID=LIVE_STREAM_ID, header=source.header, values=list(source.values))
                for tail in self._tails:
                    tail.put_nowait(frame)
            index += 1

    async def consume(self, time_range: TimeRange) -> AsyncIterator[PmuFrame]:
        tail: asyncio.Queue[PmuFrame] = asyncio.Queue()
        self._tails.append(tail)
        try:
            while True:
                if time_range.end is None:
                    frame = await tail.get()
                else:
                    remaining = (time_range.end - utcnow()).total_seconds()
                    try:
                        frame = await asyncio.wait_for(tail.get(), max(remaining, 0.0))
                    except TimeoutError:
                        return
                if time_range.end is not None and frame.timestamp >= time_range.end:
                    return
                if time_range.contains(frame.timestamp):
                    yield frame
        finally:
            self._tails.remove(tail)
