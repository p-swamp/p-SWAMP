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
  It is transport metadata, not a message field. A run publishes under
  ``<run>#<run id>.<stream>`` (``pswamp_core.keys``); a subscriber to
  ``<run>`` hears all of those.
- The app is part of the topic, so two apps reading the same class under the
  same key never hear each other.
- A topic carries exactly one class: a subscriber to ``ResultEnvelope`` hears
  no subclass, as on a broker. Two classes of one name have the same topic, so
  ``subscribe`` refuses the second (and ``Pipeline`` refuses to declare both).
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
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, ClassVar

from pswamp_models.common import Command, ErrorEvent, ModuleStarted, PipelineClosed, ResultEnvelope, stamp_sent_at

from ..keep_up import KeepUp, KeepUpMonitor
from ..log import get_logger
from ..settings import Configurable, MissingSettingError, load_class, parse_specs
from ..subscription import Overflow, Subscription
from ..util.tasks import cancel_and_wait

if TYPE_CHECKING:
    from pswamp_models.common import DataModel

__all__ = [
    "CONTROL_DEADLINE_S",
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


def _percentiles(seconds: Iterable[float]) -> tuple[float, float, float]:
    """The median, the 95th percentile and the maximum of ``seconds``, in milliseconds."""
    ordered = sorted(seconds)
    if not ordered:
        return 0.0, 0.0, 0.0

    def at(fraction: float) -> float:
        return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))] * 1000

    return at(0.5), at(0.95), ordered[-1] * 1000


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
        if topic not in self.topics or self.key is None:
            return topic in self.topics
        return key == self.key or key.startswith(self.key + "#")

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
        #: Every topic this process has subscribed to, and the class it carries.
        self._models: dict[str, type[DataModel]] = {}
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

    def timing(self) -> str | None:
        """Where the last publishes spent their time, if this transport keeps track:
        the outbox adds it to its drop report."""
        return None

    def subscribe(
        self,
        *models: type[DataModel],
        app: str,
        key: str | None = None,
        overflow: Overflow = Overflow.DROP_OLDEST,
        maxsize: int = 256,
    ) -> TransportSubscription:
        """A queue over the topics of ``models`` in ``app``, for ``key`` or every key.
        A run's key (``42``) takes every key of that run (``42#…``).

        Raises ``ValueError`` for a class whose topic already carries another
        class (two classes of one name): a topic carries one class.
        """
        if not models:
            raise ValueError("subscribe needs at least one message class")
        topics: dict[str, type[DataModel]] = {}
        for model in models:
            topic = self.topic(model, app)
            carried = self._models.setdefault(topic, model)
            if carried is not model:
                raise ValueError(
                    f"topic {topic} carries {carried.__module__}.{carried.__qualname__}; "
                    f"{model.__module__}.{model.__qualname__} cannot share it"
                )
            topics[topic] = model
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
    would: every message goes through JSON (subscribers get an equal copy, of
    the class they subscribed with), reaches only the exact topic of its
    class, and is stamped with its send time.
    """

    in_process = True

    def __init__(self, name: str = "memory") -> None:
        super().__init__(name)

    async def publish(self, message: DataModel, *, app: str, key: str) -> None:
        topic = self.topic(type(message), app)
        wanted = [s for s in self._subscriptions if s.wants(topic, key)]
        if wanted:
            received = self._models[topic].model_validate_json(message.model_dump_json())
            stamp_sent_at(received, time.time())
            for subscription in wanted:
                subscription.offer((key, received))


#: Never dropped by a full outbox: what changes something, or reports it.
_CONTROL = (Command, ErrorEvent, PipelineClosed, ModuleStarted)

#: How long a control message may wait to be published. Past it, it is given
#: up and reported: a command applied long after its 200 is worse than one
#: reported lost.
CONTROL_DEADLINE_S = 10.0

#: The first wait before a control message is published again; it doubles, to
#: at most ``_MAX_RETRY_S``.
_RETRY_S = 0.25
_MAX_RETRY_S = 2.0

#: How many of the latest send times an outbox keeps, for its drop report.
_TIMED_SENDS = 512

#: How often an outbox checks how late the event loop wakes it.
_LAG_PROBE_S = 0.05


def _is_control(message: DataModel) -> bool:
    """``_CONTROL``, or a result that answers a command: someone asked for it."""
    return isinstance(message, _CONTROL) or (isinstance(message, ResultEnvelope) and message.request_id is not None)


class Outbox:
    """A synchronous sink onto the transport, for one app, under ``key`` or
    a key given per message (``publish(message, key=...)``).

    ``publish`` queues and returns; a task sends in order. When more than
    ``maxsize`` data messages wait, the oldest is dropped (a live stream would
    rather lose a stale frame than fall further behind), and reported under
    ``keep_up``. A data message the transport refuses is dropped too.

    Control messages (commands, answers to commands, errors and
    ``PipelineClosed``), and a data message published with ``keep=True`` (a
    report, which a later message does not make stale), are never dropped for
    room. One the transport refuses
    is published again, with backoff, until ``deadline`` seconds after it was
    queued. Then it is given up, logged, and handed to ``on_undelivered`` with
    the last error (``None`` when it waited in the queue past its deadline and
    was never tried). So a command is applied within ``deadline`` of its
    acknowledgement, or reported.
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
        deadline: float = CONTROL_DEADLINE_S,
        on_undelivered: Callable[[DataModel, Exception | None], None] | None = None,
    ) -> None:
        self.transport = transport
        self.app = app
        self.key = key
        self.maxsize = maxsize
        self.deadline = deadline
        self.on_undelivered = on_undelivered
        #: Each queued message, with when (monotonic) it was queued, its key, and whether it is kept
        #: (never dropped for room, and published again until its deadline).
        self._queue: deque[tuple[DataModel, float, str, bool]] = deque()
        self._data = 0
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._probe: asyncio.Task | None = None
        self.published = self.failed = self.dropped = self.undelivered = 0
        #: How long the transport took over each of the last sends (seconds).
        self._send_times: deque[float] = deque(maxlen=_TIMED_SENDS)
        #: How late the event loop woke the probe each time (seconds).
        self._lags: deque[float] = deque(maxlen=_TIMED_SENDS)
        self.monitor = KeepUpMonitor(
            app, "cannot publish as fast as it produces", keep_up, label=label, describe=self._timing
        )

    def _timing(self) -> str | None:
        """Where the time goes, for a drop report: how long the last sends took (the outbox
        sends one message at a time, so its rate cannot exceed one per send time), the
        transport's own steps, and how late the event loop runs what it is asked to."""
        parts = []
        if self._send_times:
            median, p95, worst = _percentiles(self._send_times)
            sends = f"last {len(self._send_times)} sends took {median:.0f} ms median, {p95:.0f} ms p95, {worst:.0f} ms max"
            steps = self.transport.timing()
            parts.append(f"{sends} ({steps})" if steps else sends)
        if self._lags:
            median, p95, worst = _percentiles(self._lags)
            parts.append(f"event loop lag {median:.0f} ms median, {p95:.0f} ms p95, {worst:.0f} ms max")
        return "; ".join(parts) or None

    async def _watch_loop(self) -> None:
        """Note how late the event loop wakes this task: what a busy loop does to every send."""
        loop = asyncio.get_running_loop()
        while True:
            due = loop.time() + _LAG_PROBE_S
            await asyncio.sleep(_LAG_PROBE_S)
            self._lags.append(max(0.0, loop.time() - due))

    def publish(self, message: DataModel, key: str | None = None, *, keep: bool = False) -> None:
        """Queue ``message``, under ``key`` or the outbox's key as it is now;
        ``keep``: never drop it for room, as a control message. Never blocks."""
        kept = keep or _is_control(message)
        if not kept and self._data >= self.maxsize:
            self._drop_oldest_data()
        self._queue.append((message, time.monotonic(), self.key if key is None else key, kept))
        self._data += 0 if kept else 1
        self._wake.set()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name=f"{self.app}@{self.key}.outbox")
            self._probe = asyncio.create_task(self._watch_loop(), name=f"{self.app}@{self.key}.outbox.lag")

    async def close(self, timeout: float = 2.0) -> None:
        """Send what is still queued (a ``PipelineClosed``, say), then stop."""
        tasks = [t for t in (self._task, self._probe) if t is not None]
        self._task = self._probe = None
        if tasks:
            await cancel_and_wait(*tasks)
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(timeout):
                while self._queue:
                    await self._send(*self._pop())

    def _drop_oldest_data(self) -> None:
        for i, (_, _, _, kept) in enumerate(self._queue):
            if not kept:
                del self._queue[i]
                self._data -= 1
                self.dropped += 1
                self.monitor.note(self, 1)
                return

    def _pop(self) -> tuple[DataModel, float, str, bool]:
        message, queued_at, key, kept = self._queue.popleft()
        self._data -= 0 if kept else 1
        return message, queued_at, key, kept

    async def _run(self) -> None:
        while True:
            while not self._queue:
                self._wake.clear()
                await self._wake.wait()
            await self._send(*self._pop())

    async def _send(self, message: DataModel, queued_at: float, key: str, kept: bool) -> None:
        if not kept:
            with contextlib.suppress(Exception):  # counted and logged by _attempt
                await self._attempt(message, key)
            return
        give_up_at, wait, error = queued_at + self.deadline, _RETRY_S, None
        while time.monotonic() < give_up_at:
            try:
                await self._attempt(message, key)
                return
            except Exception as failure:
                error = failure
            await asyncio.sleep(min(wait, max(0.0, give_up_at - time.monotonic())))
            wait = min(wait * 2, _MAX_RETRY_S)
        self._give_up(message, error)

    async def _attempt(self, message: DataModel, key: str) -> None:
        started = time.perf_counter()
        try:
            await self.transport.publish(message, app=self.app, key=key)
        except Exception as error:
            self.failed += 1
            if self.failed <= 3 or self.failed % 50 == 0:
                logger.warning(
                    "%s@%s: could not publish %s (%d failed): %s",
                    self.app, key, type(message).__name__, self.failed, error,
                )
            raise
        finally:
            self._send_times.append(time.perf_counter() - started)
        self.published += 1

    def _give_up(self, message: DataModel, error: Exception | None) -> None:
        self.undelivered += 1
        logger.warning(
            "%s@%s: gave up on %s after %g s: %s", self.app, self.key, type(message).__name__, self.deadline,
            error if error is not None else "it waited in the queue past its deadline",
        )
        if self.on_undelivered is not None:
            try:
                self.on_undelivered(message, error)
            except Exception:
                logger.exception("%s@%s: reporting an undelivered %s failed", self.app, self.key, type(message).__name__)


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
