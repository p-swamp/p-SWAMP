"""Helpers shared by the core's tests."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel

from pswamp_core.datagateway import DataClient, TimeRange
from pswamp_core.messages import DataModel, PmuFrame, PmuHeader, ResultEnvelope
from pswamp_core.util.time import utcnow

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
