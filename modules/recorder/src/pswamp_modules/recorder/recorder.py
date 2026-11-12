"""``Recorder``: records the ``PmuFrame`` stream it is fed, and plays it back as a history source."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

from pswamp_core.playable import Playable
from pswamp_core.settings import EnvSetting
from pswamp_core.sources import SourceModule
from pswamp_core.time_range import TimeRange
from pswamp_models.pmu import PmuFrame

from .store import Store

__all__ = ["Recorder"]


class Recorder(Playable, SourceModule):
    """Fed ``PmuFrame``s (``process``), it keeps them under ``DIR``; as a source it reads them back."""

    name = "recorder"
    kind = "history"
    blocking = True
    inputs = (PmuFrame,)
    outputs = (PmuFrame,)
    env_settings = (
        EnvSetting("DIR", "The folder the recordings are kept in", required=True, kind="path"),
        EnvSetting("FEED", "The live source it records; none: it only plays back what it holds"),
        EnvSetting("ROLL_HOURS", "Hours of frames after which a new segment starts", default="6", kind="float"),
        EnvSetting("FLUSH_SECONDS", "Seconds between writes to disk", default="1", kind="seconds"),
        EnvSetting("MAX_BYTES", "Bytes kept: the oldest segments go first", default=str(5 * 1024**3), kind="int"),
    )

    def __init__(self, source: str | None = None, **settings: Any) -> None:
        super().__init__(source, **settings)
        self.store = Store(
            self.settings.dir / self.source,
            roll=timedelta(hours=self.settings.roll_hours),
            flush_every=self.settings.flush_seconds,
            max_bytes=self.settings.max_bytes,
        )

    def process(self, frame: PmuFrame) -> None:
        self.store.append(frame)

    def reset(self) -> None:
        """The run's stream starts over: what comes next is a segment of its own."""
        self.store.roll_over()

    async def teardown(self) -> None:
        await asyncio.to_thread(self.store.flush)

    def flush(self) -> None:
        self.store.flush()

    @property
    def idle_flush_seconds(self) -> float:
        """How long a quiet feed may leave frames buffered: the run flushes the recorder after this much silence."""
        return max(self.store.flush_every.total_seconds(), 0.05)

    def read(self, start: datetime | None = None, end: datetime | None = None) -> Iterator[PmuFrame]:
        return self.store.read(start, end)

    def coverage(self) -> TimeRange | None:
        self.store.flush()
        bounds = self.store.bounds()
        return None if bounds is None else TimeRange(bounds[0], bounds[1] + timedelta(microseconds=1))
