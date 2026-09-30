# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The transport: keyed publish/subscribe between the parts of a pipeline.

**One topic per message class, per app, and a key on every record**::

    await transport.publish(frame, app="pmu-test-streamer", key="42")    # topic pmu-test-streamer.pmu.frame
    with transport.subscribe(FrameStatsResult, app="pmu-test-streamer", key="42") as results:
        async for key, result in results: ...                           # key "42" only
    with transport.subscribe(PmuFrame, app="pmu-test-streamer") as frames:
        async for key, frame in frames: ...                             # every key

- The key says which run a record belongs to (a client id, or a live source).
  It is transport metadata, not a message field.
- The app is part of the topic, so two apps reading the same class under the
  same key never hear each other.
- A topic carries exactly one class: a subscriber to ``ResultEnvelope`` hears
  no subclass, as on a broker.
- A subscriber hears only what is published after it subscribes. Nothing is
  replayed; a frame carries its own layout, so a late subscriber needs nothing
  more.

Implementations: ``InMemoryTransport`` here (one process, no port), and
``pswamp_core.transport.kafka.KafkaTransport``. A new one (NATS, say)
implements ``publish`` and, if messages arrive from elsewhere, ``_watch``, and
passes the same test suite. The deployment picks one with ``PSWAMP_TRANSPORT``
(``transport_from_env``); nothing else changes.

Publishers (the player, a module) are synchronous and never wait on a broker:
each publishes into an ``Outbox``, which a task drains onto the transport.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
from abc import ABC, abstractmethod
from collections import deque
from typing import TYPE_CHECKING, ClassVar

from ..keep_up import KeepUp, KeepUpMonitor
from ..log import get_logger
from ..messages.commands import Command
from ..messages.control import PipelineClosed
from ..messages.data_model import stamp_sent_at
from ..messages.errors import ErrorEvent
from ..settings import Configurable, MissingSettingError, load_class, parse_specs
from ..subscription import Overflow, Subscription
from ..util.tasks import cancel_and_wait

if TYPE_CHECKING:
    from ..messages.data_model import DataModel

__all__ = [
    "TRANSPORT_VARIABLE",
    "InMemoryTransport",
    "Outbox",
    "Transport",
    "TransportSubscription",
    "transport_from_env",
]

#: Names the deployment's transport; unset means in-memory.
TRANSPORT_VARIABLE = "PSWAMP_TRANSPORT"

logger = get_logger("pswamp_core.transport")


class TransportSubscription(Subscription):
    """A queue of ``(key, message)`` over some topics of one app, for one key
    (``key=...``) or every key (``key=None``)."""

    def __init__(
        self,
        transport: Transport,
        topics: dict[str, type[DataModel]],
        key: str | None,
        overflow: Overflow,
        maxsize: int,
    ) -> None:
        super().__init__(transport, tuple(topics.values()), overflow, maxsize)
        self._transport = transport
        self.topics = topics
        self.key = key

    def wants(self, topic: str, key: str) -> bool:
        return topic in self.topics and (self.key is None or key == self.key)

    async def ready(self, timeout: float | None = None) -> None:
        """Wait until this process receives every topic here. Needed by a
        subscriber that publishes right after subscribing and expects to hear
        the answer; a broker's consumer joins a topic at its end."""
        events = [self._transport._ready[t] for t in self.topics if t in self._transport._ready]
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in events)), timeout)


class Transport(Configurable, ABC):
    """Keyed publish/subscribe, plus the fan-out to subscriber queues.

    A subclass implements ``publish``, and ``_watch`` when messages reach it
    from a broker (start receiving a topic; call ``_deliver`` per message).
    """

    #: True when both ends of every topic are in this process, so the server
    #: must host the modules itself.
    in_process: ClassVar[bool] = False

    def __init__(self, name: str = "transport") -> None:
        self.name = name
        self._subscriptions: list[TransportSubscription] = []
        #: Set per topic once this process is receiving it.
        self._ready: dict[str, asyncio.Event] = {}

    def topic(self, model: type[DataModel], app: str) -> str:
        """``<app>.<model.topic>``."""
        return f"{app}.{model.topic}"

    async def open(self) -> None:
        """Connect. Idempotent: everything in a process shares one transport."""

    async def close(self) -> None:
        """Disconnect; open subscriptions end."""
        self._ready.clear()
        for subscription in list(self._subscriptions):
            subscription.close()

    @abstractmethod
    async def publish(self, message: DataModel, *, app: str, key: str) -> None:
        """Send ``message`` on its class's topic in ``app``, under ``key``.
        Raises on failure."""

    def subscribe(
        self,
        *models: type[DataModel],
        app: str,
        key: str | None = None,
        overflow: Overflow = Overflow.DROP_OLDEST,
        maxsize: int = 256,
    ) -> TransportSubscription:
        """A queue over the topics of ``models`` in ``app``, for ``key`` or every key."""
        if not models:
            raise ValueError("subscribe needs at least one message class")
        topics = {self.topic(model, app): model for model in models}
        subscription = TransportSubscription(self, topics, key, overflow, maxsize)
        self._subscriptions.append(subscription)
        for topic, model in topics.items():
            self._watch(topic, model)
        return subscription

    def _watch(self, topic: str, model: type[DataModel]) -> None:
        """Start receiving ``topic`` in this process. Nothing to do when every
        message arrives through ``publish``."""

    def _deliver(self, topic: str, key: str, message: DataModel) -> None:
        for subscription in list(self._subscriptions):
            if subscription.wants(topic, key):
                subscription.offer((key, message))

    def _detach(self, subscription: Subscription) -> None:
        if subscription in self._subscriptions:
            self._subscriptions.remove(subscription)  # type: ignore[arg-type]


class InMemoryTransport(Transport):
    """A broker with no port: publishing delivers on the same loop.

    It behaves as a broker does, so a hermetic test catches what a deployment
    would: every message goes through JSON (subscribers get an equal copy),
    reaches only the exact topic of its class, and is stamped with its send time.
    """

    in_process = True

    def __init__(self, name: str = "memory") -> None:
        super().__init__(name)

    async def publish(self, message: DataModel, *, app: str, key: str) -> None:
        topic = self.topic(type(message), app)
        wanted = [s for s in self._subscriptions if s.wants(topic, key)]
        if wanted:
            received = type(message).model_validate_json(message.model_dump_json())
            stamp_sent_at(received, time.time())
            for subscription in wanted:
                subscription.offer((key, received))


#: Never dropped by a full outbox: what changes something, or reports it.
_CONTROL = (Command, ErrorEvent, PipelineClosed)


class Outbox:
    """A synchronous sink onto the transport, for one app and key.

    ``publish`` queues and returns; a task sends in order. When more than
    ``maxsize`` data messages wait, the oldest is dropped (a live stream would
    rather lose a stale frame than fall further behind), and reported under
    ``keep_up``. Commands, errors and ``PipelineClosed`` are never dropped.
    """

    def __init__(
        self,
        transport: Transport,
        *,
        app: str,
        key: str,
        maxsize: int = 64,
        keep_up: KeepUp | None = None,
        label: str | None = None,
    ) -> None:
        self.transport = transport
        self.app = app
        self.key = key
        self.maxsize = maxsize
        self._queue: deque[DataModel] = deque()
        self._data = 0
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self.published = self.failed = self.dropped = 0
        self.monitor = KeepUpMonitor(app, "cannot publish as fast as it produces", keep_up, label=label)

    def publish(self, message: DataModel) -> None:
        """Queue ``message``. Never blocks."""
        control = isinstance(message, _CONTROL)
        if not control and self._data >= self.maxsize:
            self._drop_oldest_data()
        self._queue.append(message)
        self._data += 0 if control else 1
        self._wake.set()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name=f"{self.app}@{self.key}.outbox")

    async def close(self, timeout: float = 2.0) -> None:
        """Send what is still queued (a ``PipelineClosed``, say), then stop."""
        task, self._task = self._task, None
        if task is not None:
            await cancel_and_wait(task)
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(timeout):
                while self._queue:
                    await self._send(self._pop())

    def _drop_oldest_data(self) -> None:
        for i, queued in enumerate(self._queue):
            if not isinstance(queued, _CONTROL):
                del self._queue[i]
                self._data -= 1
                self.dropped += 1
                self.monitor.note(self, 1)
                return

    def _pop(self) -> DataModel:
        message = self._queue.popleft()
        self._data -= 0 if isinstance(message, _CONTROL) else 1
        return message

    async def _run(self) -> None:
        while True:
            while not self._queue:
                self._wake.clear()
                await self._wake.wait()
            await self._send(self._pop())

    async def _send(self, message: DataModel) -> None:
        try:
            await self.transport.publish(message, app=self.app, key=self.key)
        except Exception as error:
            self.failed += 1
            if self.failed <= 3 or self.failed % 50 == 0:
                logger.warning(
                    "%s@%s: could not publish %s (%d failed): %s",
                    self.app, self.key, type(message).__name__, self.failed, error,
                )
            return
        self.published += 1


def transport_from_env(variable: str = TRANSPORT_VARIABLE) -> Transport:
    """The transport ``variable`` names (``name:module.path:Class`` plus its
    ``{NAME}_{SETTING}`` block), or an ``InMemoryTransport`` when unset.

    The server and every worker read the same variable, so they cannot be
    configured apart.
    """
    spec = os.environ.get(variable, "").strip()
    if not spec:
        return InMemoryTransport()
    ((name, module_path, class_name), *rest) = parse_specs(variable, spec)
    if rest:
        raise MissingSettingError(f"{variable} names more than one transport")
    return load_class(variable, module_path, class_name, Transport).from_env(name)
