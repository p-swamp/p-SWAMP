"""Helpers shared by the core's tests."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel

from pswamp_core.datagateway import DataClient
from pswamp_core.playable import Playable
from pswamp_core.sources import SourceModule
from pswamp_core.time_range import TimeRange
from pswamp_core.util.time import utcnow
from pswamp_models.common import DataModel, ResultEnvelope
from pswamp_models.pmu import PmuFrame, PmuHeader

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def at(seconds: float) -> datetime:
    """``seconds`` after ``T0``."""
    return T0 + timedelta(seconds=seconds)


HEADER = PmuHeader(
    station=["A", "A", "B", "B"],
    channel=["V", "f", "V", "f"],
    measurement=["V_Magnitude", "f", "V_Magnitude", "f"],
    units=["kV", "Hz", "kV", "Hz"],
    data_rate=20.0,
)


def frame(seconds: float, f: float = 50.0, header: PmuHeader = HEADER) -> PmuFrame:
    """A frame at ``at(seconds)`` with every frequency column at ``f``."""
    values = [f if m == "f" else 400.0 for m in header.measurement]
    return PmuFrame(timestamp=at(seconds), mRID="test", header=header, values=values)


class Measurement(DataModel):
    """A minimal message for tests."""

    version: Literal["v1"] = "v1"
    value: float = 0.0


class Number(BaseModel):
    value: float


class NumberResult(ResultEnvelope[Number]):
    version: Literal["v1"] = "v1"


def measurement(i: int, seconds: float | None = None) -> Measurement:
    """``Measurement`` number ``i`` (mRID ``m<i>``)."""
    return Measurement(mRID=f"m{i}", timestamp=at(i if seconds is None else seconds), value=float(i))


async def take(subscription, n: int, timeout: float = 5.0) -> list:
    """The next ``n`` items of ``subscription``, or fail after ``timeout``."""
    async def read():
        return [await subscription.get() for _ in range(n)]

    return await asyncio.wait_for(read(), timeout)


class Recorder:
    """A sink that keeps what is published into it."""

    def __init__(self) -> None:
        self.published: list = []

    def publish(self, message) -> None:
        self.published.append(message)

    def of(self, cls) -> list:
        return [m for m in self.published if isinstance(m, cls)]

    async def wait_for(self, cls, n: int = 1, timeout: float = 5.0) -> list:
        """The first ``n`` messages of ``cls``, waiting up to ``timeout``."""
        async def poll():
            while len(self.of(cls)) < n:
                await asyncio.sleep(0.005)
            return self.of(cls)[:n]

        return await asyncio.wait_for(poll(), timeout)


class _NoOwner:
    def _detach(self, subscription) -> None:
        return


def queue(*models, overflow=None, maxsize: int = 64):
    """A free-standing subscription to feed a module or an inbox by hand."""
    from pswamp_core.subscription import Overflow, Subscription

    return Subscription(_NoOwner(), models, overflow or Overflow.GROW, maxsize)


class ListClient(DataClient):
    """A history client over a list of frames."""

    kind = "history"

    def __init__(self, name: str = "list", frames=None) -> None:
        super().__init__(name)
        self.frames = list(frames if frames is not None else [frame(i / 20) for i in range(20)])
        self.opened = self.closed = 0

    async def open(self) -> None:
        self.opened += 1

    async def close(self) -> None:
        self.closed += 1

    async def coverage(self) -> TimeRange | None:
        if not self.frames:
            return None
        return TimeRange(self.frames[0].timestamp, self.frames[-1].timestamp + timedelta(seconds=0.05))

    async def consume(self, time_range: TimeRange):
        for record in self.frames:
            if time_range.contains(record.timestamp):
                yield record


class TickingClient(DataClient):
    """A live client: a frame stamped now, every ``interval`` seconds."""

    kind = "live"

    def __init__(self, name: str = "ticker", interval: float = 0.02) -> None:
        super().__init__(name)
        self.interval = interval
        self.opened = 0

    async def open(self) -> None:
        self.opened += 1

    async def consume(self, time_range: TimeRange):
        while True:
            await asyncio.sleep(self.interval)
            now = utcnow()
            if time_range.end is not None and now >= time_range.end:
                return
            yield frame(0).model_copy(update={"timestamp": now})


def install_modules(monkeypatch, **modules: str) -> None:
    """Make ``pswamp_core.pipeline_config`` see exactly these modules as
    installed: entry-point name → ``module.path:Class``, as a module project's
    ``[project.entry-points."pswamp.modules"]`` would declare them."""
    from importlib.metadata import EntryPoint

    from pswamp_core import pipeline_config

    points = {name: EntryPoint(name, value, pipeline_config.MODULES_GROUP) for name, value in modules.items()}
    monkeypatch.setattr(pipeline_config, "available_modules", lambda: dict(points))


def write_pipeline(path, text: str):
    """``text`` written to ``path``, which is returned."""
    path.write_text(text, encoding="utf-8")
    return path


class ListSource(Playable, SourceModule):
    """A playable history source over a list of frames, written as sync ``read``."""

    name = "list-source"
    kind = "history"

    def __init__(self, source: str = "list", frames=None) -> None:
        super().__init__(source)
        self.frames = list(frames if frames is not None else [frame(i / 20) for i in range(20)])
        self.opened = self.closed = 0

    def open(self) -> None:
        self.opened += 1

    def close(self) -> None:
        self.closed += 1

    def coverage(self) -> TimeRange | None:
        if not self.frames:
            return None
        return TimeRange(self.frames[0].timestamp, self.frames[-1].timestamp + timedelta(seconds=0.05))

    def read(self, start=None, end=None):
        for record in self.frames:
            if TimeRange(start, end).contains(record.timestamp):
                yield record


class AsyncListSource(SourceModule):
    """The same history, written as ``aread`` and ``acoverage``."""

    name = "async-list-source"
    kind = "history"

    def __init__(self, source: str = "async-list", frames=None) -> None:
        super().__init__(source)
        self.frames = list(frames if frames is not None else [frame(i / 20) for i in range(20)])

    async def acoverage(self) -> TimeRange | None:
        return TimeRange(self.frames[0].timestamp, self.frames[-1].timestamp + timedelta(seconds=0.05))

    async def aread(self, start=None, end=None):
        for record in self.frames:
            await asyncio.sleep(0)
            if TimeRange(start, end).contains(record.timestamp):
                yield record


class TickingSource(SourceModule):
    """A live source, written as ``aread``: a frame stamped now, every ``interval`` seconds."""

    name = "ticking-source"
    kind = "live"

    def __init__(self, source: str = "ticker", interval: float = 0.02) -> None:
        super().__init__(source)
        self.interval = interval
        self.opened = 0

    def open(self) -> None:
        self.opened += 1

    async def aread(self, start=None, end=None):
        while True:
            await asyncio.sleep(self.interval)
            now = utcnow()
            if end is not None and now >= end:
                return
            yield frame(0).model_copy(update={"timestamp": now})
