# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""A consumer's queue, and what happens when the consumer is slow.

Every subscription in the core is a ``Subscription``: an async-iterable queue
on the event loop with an ``Overflow`` policy. Its *owner* (a transport, a
module host) offers it messages and is told when it closes.
"""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol

from .log import get_logger

if TYPE_CHECKING:
    from pswamp_models.common import DataModel

__all__ = ["Overflow", "Sink", "Subscription"]

logger = get_logger("pswamp_core.subscription")


class Sink(Protocol):
    """Anything a message can be handed to synchronously, on the loop: what the
    player and a module publish into."""

    def publish(self, message: DataModel) -> None: ...


class _Owner(Protocol):
    def _detach(self, subscription: Subscription) -> None: ...


class Overflow(str, Enum):
    """What a full queue does.

    ``DROP_OLDEST``: bounded; the oldest unread item makes room. Right for a
    live stream, where a stale frame is worth less than a fresh one.
    ``GROW``: unbounded. Right for commands, where every one matters.
    """

    DROP_OLDEST = "drop_oldest"
    GROW = "grow"


_CLOSED = object()


class Subscription:
    """One consumer's queue. Iterate it, or poll with ``get_nowait``; close it
    (or leave its ``with`` block) to detach it from its owner."""

    def __init__(
        self, owner: _Owner, models: tuple[type[DataModel], ...], overflow: Overflow, maxsize: int
    ) -> None:
        self._owner = owner
        self.models = models
        self.overflow = overflow
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=0 if overflow is Overflow.GROW else maxsize)
        self.dropped = 0
        self._closed = False

    def offer(self, item: Any) -> None:
        """Deliver one item. Never blocks."""
        if self._closed:
            return
        if self._queue.full():
            self._drop_one()
        self._queue.put_nowait(item)

    def _drop_one(self) -> None:
        try:
            self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return
        self.dropped += 1
        if self.dropped % 50 == 1:
            names = ",".join(model.__name__ for model in self.models)
            logger.warning("subscriber on %s is not keeping up; %d dropped", names, self.dropped)

    async def get(self) -> Any:
        """The next item; ``StopAsyncIteration`` once closed."""
        item = await self._queue.get()
        if item is _CLOSED:
            self._queue.put_nowait(_CLOSED)
            raise StopAsyncIteration
        return item

    def get_nowait(self) -> Any | None:
        """The next item, or ``None`` if there is none."""
        try:
            item = self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None
        if item is _CLOSED:
            self._queue.put_nowait(_CLOSED)
            return None
        return item

    def __aiter__(self) -> Subscription:
        return self

    async def __anext__(self) -> Any:
        return await self.get()

    def close(self) -> None:
        """Detach from the owner and end any pending read."""
        if self._closed:
            return
        self._closed = True
        self._owner._detach(self)
        if self._queue.full():
            self._drop_one()
        self._queue.put_nowait(_CLOSED)

    def __enter__(self) -> Subscription:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
