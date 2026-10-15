# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``ModuleHost``: runs a module, one instance per run, off the transport.

    topic <app>.<input>,   key k ─▶ the instance for k's run ─▶ Module.arun
    topic <app>.<command>, key k ─▶ its command inbox        ─▶ Module.ahandle
    topic <app>.<output>,  key k ◀─ each of its outputs (and ErrorEvents)

The host subscribes to every input of the module. Inputs go to the instance's
queue, which applies the module's overflow policy, and ``serve_module`` reads
them one at a time. A module joining named inputs queues only its trigger: any
other input only replaces the newest of its kind in the join (``observe``), so
a fast stream never backs up behind a slow trigger. Each output of a call is
published on its own topic, under the key the input came with.

An instance is built on the first message of its run (``StreamKey.run``), so
a per-client run costs one instance per client, and a shared live run one in
total. A key also carries its run's id (``pswamp_core.keys``): a message of a
newer run of the same client (after a server restart, say) replaces the
instance with a fresh one, and a late message of an older run is dropped. An
instance is dropped when its run publishes ``PipelineClosed``, or, if that was
lost, after ``idle_seconds`` with nothing for it. Its ``teardown`` is called
then.

A key's stream number goes up each time the run's stream starts over (a seek,
a switch, a loop). On the first input of a new stream the host empties the
instance's queue, resets its join, and has ``serve_module`` call its
``reset`` before that input; an input of an older stream (sent before the
seek, still on its way) is dropped. A call's outputs go under the key of the
input it was for, so a module reading them (a chain) sees the stream too.
Commands are not tied to a stream: a play sent while a seek is still pending
applies.

An instance that fails (its ``setup`` raises, say) is logged, reported as an
``ErrorEvent`` under its key, and dropped. The first message for that key
after ``retry_seconds`` builds a new one; what arrives before is ignored.

With the in-memory transport the server runs the hosts itself; with a broker a
worker does (``pswamp_core.worker``). The module cannot tell the difference.

A module that ``reads_sources`` gets a ``SourceSet`` of its own per instance,
built by the pipeline's factory from the same configuration the server reads.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from pswamp_models.common import ErrorEvent, PipelineClosed

from .command_routing import CommandInbox, concrete_commands
from .keep_up import KeepUpMonitor
from .keys import StreamKey
from .log import get_logger
from .subscription import Overflow, Subscription
from .transport import Outbox
from .util.tasks import cancel_and_wait, finish
from .util.time import utcnow

if TYPE_CHECKING:
    from collections.abc import AsyncIterable

    from pswamp_models.common import Command, DataModel

    from .modules import Module
    from .sources import SourceSet
    from .subscription import Sink
    from .transport import Transport, TransportSubscription

__all__ = [
    "DEFAULT_IDLE_SECONDS",
    "DEFAULT_RETRY_SECONDS",
    "ModuleHost",
    "command_inbox",
    "serve_hosts",
    "serve_module",
]

logger = get_logger("pswamp_core.host")

DEFAULT_IDLE_SECONDS = 300.0

#: How long a key is left alone after its instance failed. Without it a
#: ``setup`` that always fails would be rebuilt for every frame.
DEFAULT_RETRY_SECONDS = 5.0

#: The shared feed of one topic, across keys: only a hand-off to each key's
#: own queue, which applies the module's overflow policy.
_FEED_MAXSIZE = 1024


async def serve_module(module: Module, inputs: Subscription, out: Sink, *, slot: _Slot | None = None) -> None:
    """Feed ``module`` from ``inputs`` and publish its outputs into ``out``,
    until cancelled or ``inputs`` closes. A failing call, or an output that is
    undeclared or does not fit its envelope, is logged, reported as an
    ``ErrorEvent``, and the next input is read. Falling behind is reported
    per the module's ``keep_up``. With a host's ``slot``: a reset it has due
    runs before the next input, and each call's outputs go under its input's
    key."""
    if not inputs.models:
        return
    what = f"is not keeping up with {', '.join(model.topic for model in inputs.models)}"
    monitor = KeepUpMonitor(module.name, what, module.keep_up)
    async for message in inputs:
        # The queue holds only the slot's current stream (``_Slot.new_stream``
        # empties it), so its key now is the input's.
        key = None if slot is None else str(slot.key)
        if slot is not None and slot.reset_due:
            slot.reset_due = False
            try:
                await module.areset()
            except Exception as error:
                _report(module, out, key, "failed to reset", error)
        try:
            monitor.observe(inputs, message, out)
            for output in await module.arun(message):
                _publish(out, output, key)
        except Exception as error:
            _report(module, out, key, f"failed on {type(message).__name__}", error)


def _report(module: Module, out: Sink, key: str | None, what: str, error: Exception) -> None:
    logger.exception("module %s %s", module.name, what)
    event = ErrorEvent(
        timestamp=utcnow(),
        source=module.name,
        message=f"module {module.name} {what}",
        detail=f"{type(error).__name__}: {error}",
    )
    _publish(out, event, key)


def _publish(out: Sink, message: DataModel, key: str | None) -> None:
    """Into ``out``: under ``key`` when given (an ``Outbox``), as it is otherwise."""
    if key is None:
        out.publish(message)
    else:
        out.publish(message, key)  # type: ignore[call-arg]


class _Answering:
    """A module as the command inbox sees a receiver. It validates in
    ``handle``, under the instance's lock, so a command's ``validate`` and
    answer are one call: neither runs while an input is processed."""

    def __init__(self, module: Module) -> None:
        self.module = module
        self.name = module.name
        self.commands = module.commands

    def validate(self, command: Command) -> None:
        return

    async def handle(self, command: Command) -> object:
        async with self.module._calling:
            self.module.validate(command)
            return await self.module.ahandle(command)


def command_inbox(module: Module, commands: AsyncIterable[Command], out: Sink) -> CommandInbox:
    """Applies ``module``'s commands; its answers and refusals go to ``out``.
    An answer that cannot be published (undeclared, or not fitting its
    envelope) is reported as applied but unanswered."""

    def answer(command: Command, returned: object) -> None:
        for output in module.answer_of(command, returned):
            out.publish(output)

    return CommandInbox(commands, _Answering(module), out, on_result=answer)


class _Local:
    """Owner of a slot's queues, which the host fills directly."""

    def _detach(self, subscription: Subscription) -> None:
        return


class _Slot:
    """One run's module instance, with its queues, outbox and tasks."""

    def __init__(self, key: StreamKey, module: Module, transport: Transport, app: str) -> None:
        self.key = key
        self.run = key.run
        self.run_id = key.run_id
        self.module = module
        # Queues exist before the module is set up, so nothing arriving
        # meanwhile is lost.
        self.inputs = Subscription(_Local(), module.queued_inputs(), module.overflow, module.maxsize)
        self.commands = Subscription(_Local(), module.commands, Overflow.GROW, 0)
        self.out = Outbox(transport, app=app, key=str(key))
        self.inbox: CommandInbox | None = None
        self.tasks: list[asyncio.Task] = []
        self.seen = time.monotonic()
        self.set_up = False
        self.dropped = False
        #: The newest stream of the run's inputs, and whether the instance
        #: has yet to be reset for it.
        self.stream = key.stream
        self.reset_due = False

    def new_stream(self, key: StreamKey) -> None:
        """The run's stream started over: what is queued is void, the join
        forgets, and the instance is reset before its next input."""
        self.key = key
        self.stream = key.stream
        self.out.key = str(key)
        self.inputs.clear()
        self.module._reset_join()
        self.reset_due = True


class ModuleHost:
    """Runs one instance of a module per run.

    Args:
        module: The module class, or a factory building a fresh instance.
        transport: The process's transport.
        app: The app whose topics the module is reached on.
        idle_seconds: How long a key may go without a message before its
            instance is dropped, in case its ``PipelineClosed`` never arrives.
        retry_seconds: How long a key is left alone after its instance failed.
        sources: Builds a ``SourceSet`` for an instance that ``reads_sources``.
    """

    def __init__(
        self,
        module: type[Module] | Callable[[], Module],
        transport: Transport,
        *,
        app: str,
        idle_seconds: float = DEFAULT_IDLE_SECONDS,
        retry_seconds: float = DEFAULT_RETRY_SECONDS,
        sources: Callable[[], SourceSet] | None = None,
    ) -> None:
        self._factory = module
        self._sources = sources
        self.transport = transport
        self.app = app
        self.idle_seconds = idle_seconds
        self.retry_seconds = retry_seconds
        template = module()
        self.name = template.name
        self.inputs = template.queued_inputs()
        #: The inputs that only update the newest of their kind (a join's others).
        self.observed = tuple(m for m in template.input_models() if m not in self.inputs)
        self.outputs = template.outputs
        self.commands = concrete_commands(type(template).__name__, template.commands)
        #: Per run: its instance.
        self._slots: dict[str, _Slot] = {}
        #: The instances that failed or were replaced, for ``_reap`` to drop.
        self._retired: asyncio.Queue[tuple[_Slot, str]] = asyncio.Queue()
        #: Per run whose instance failed: when (monotonic) it may be rebuilt.
        self._retry_at: dict[str, float] = {}

    def keys(self) -> list[str]:
        """The runs with a running instance."""
        return list(self._slots)

    async def serve(self) -> None:
        """Consume the module's topics and run instances until cancelled."""
        await self.transport.open()
        subscribe = self.transport.subscribe
        feeds = [self._closed(subscribe(PipelineClosed, app=self.app, overflow=Overflow.GROW))]
        if self.inputs:
            feeds.append(self._feed(subscribe(*self.inputs, app=self.app, maxsize=_FEED_MAXSIZE), "inputs"))
        if self.observed:
            feeds.append(self._feed(subscribe(*self.observed, app=self.app, maxsize=_FEED_MAXSIZE), None))
        if self.commands:
            feeds.append(self._feed(subscribe(*self.commands, app=self.app, overflow=Overflow.GROW), "commands"))
        tasks = [asyncio.create_task(feed, name=f"{self.name}.host") for feed in feeds]
        tasks.append(asyncio.create_task(self._sweep(), name=f"{self.name}.host.sweep"))
        tasks.append(asyncio.create_task(self._reap(), name=f"{self.name}.host.reap"))
        logger.info(
            "hosting %s for %s: reads %s, publishes %s, commands %s, over %s",
            self.name, self.app, [m.topic for m in (*self.inputs, *self.observed)] or "nothing",
            [m.topic for m in self.outputs] or "nothing", [c.topic for c in self.commands] or "none",
            self.transport.name,
        )
        try:
            await asyncio.gather(*tasks)
        finally:
            await cancel_and_wait(*tasks, ignore=(Exception,))
            for key in list(self._slots):
                await self._evict(key, "shutdown")
            while not self._retired.empty():
                slot, reason = self._retired.get_nowait()
                if not slot.dropped:
                    await finish(self._drop(slot, reason))

    async def _feed(self, feed: TransportSubscription, queue: str | None) -> None:
        """Hand each message to its key's instance: into ``queue``, or with
        none, straight into the instance's join."""
        with feed:
            async for key, message in feed:
                stream_key = StreamKey.parse(key)
                slot = self._slot(stream_key)
                if slot is None:
                    continue
                slot.seen = time.monotonic()
                if queue == "commands":
                    slot.commands.offer(message)
                    continue
                if stream_key.stream < slot.stream:
                    continue  # sent before the run's stream started over
                if stream_key.stream > slot.stream:
                    slot.new_stream(stream_key)
                if queue is None:
                    slot.module.observe(message)
                else:
                    slot.inputs.offer(message)

    async def _closed(self, feed: TransportSubscription) -> None:
        with feed:
            async for key, closed in feed:
                closing = StreamKey.parse(key)
                slot = self._slots.get(closing.run)
                # A plain key closes whatever runs under it; otherwise not a newer run's instance.
                if slot is not None and (closing.run_id == 0 or closing.run_id >= slot.run_id):
                    await self._evict(closing.run, closed.reason)

    def _slot(self, key: StreamKey) -> _Slot | None:
        """The slot of the key's run, built if it has none or holds an older
        run; ``None`` for a message of an older run, and while the run is left
        alone after its instance failed."""
        slot = self._slots.get(key.run)
        if slot is not None:
            if key.run_id == slot.run_id:
                return slot
            if key.run_id < slot.run_id:
                return None  # a late message of the run this one replaced
            self._retire(slot, "a new run")
        if time.monotonic() < self._retry_at.get(key.run, 0.0):
            return None
        self._retry_at.pop(key.run, None)
        slot = self._slots[key.run] = _Slot(key, self._factory(), self.transport, self.app)
        slot.tasks.append(asyncio.create_task(self._run(slot), name=f"{self.name}@{key}"))
        return slot

    def _retire(self, slot: _Slot, reason: str) -> None:
        """Take ``slot`` out of service now; ``_reap`` drops it."""
        if self._slots.get(slot.run) is slot:
            del self._slots[slot.run]
        self._retired.put_nowait((slot, reason))

    async def _run(self, slot: _Slot) -> None:
        """One instance from setup until its ``run`` ends. A failure on the
        way is logged, reported under the key, and handed to ``_reap``."""
        try:
            await self._start(slot)
            await serve_module(slot.module, slot.inputs, slot.out, slot=slot)
        except Exception as error:
            logger.exception("%s: the instance for key %s failed", self.name, slot.key)
            slot.out.publish(
                ErrorEvent(
                    timestamp=utcnow(),
                    source=self.name,
                    message=f"module {self.name} stopped; it starts again in {self.retry_seconds:g} s at the earliest",
                    detail=f"{type(error).__name__}: {error}",
                )
            )
            self._retry_at[slot.run] = time.monotonic() + self.retry_seconds
            self._retire(slot, "failed")

    async def _start(self, slot: _Slot) -> None:
        module = slot.module
        slot.out.start()
        if module.reads_sources and self._sources is not None:
            module.sources = self._sources()
        await module.setup()
        slot.set_up = True
        if module.commands:
            slot.inbox = command_inbox(module, slot.commands, slot.out)
            slot.inbox.start()
        logger.info("%s: instance started for key %s (%d running)", self.name, slot.key, len(self._slots))

    async def _reap(self) -> None:
        """Drop the instances that failed or were replaced. Here, and not in
        the instance's own task (which cannot wait for its own end) or a feed
        (which would hold up every other run meanwhile)."""
        while True:
            slot, reason = await self._retired.get()
            if not slot.dropped:
                await finish(self._drop(slot, reason))

    async def _sweep(self) -> None:
        interval = max(0.05, min(self.idle_seconds / 2, 5.0))
        while True:
            await asyncio.sleep(interval)
            now = time.monotonic()
            for key in [k for k, s in self._slots.items() if s.seen < now - self.idle_seconds]:
                await self._evict(key, "idle")
            for key in [k for k, retry_at in self._retry_at.items() if retry_at <= now]:
                del self._retry_at[key]

    async def _evict(self, key: str, reason: str) -> None:
        slot = self._slots.pop(key, None)
        if slot is not None:
            # To the end even if the host is being shut down meanwhile.
            await finish(self._drop(slot, reason))

    async def _drop(self, slot: _Slot, reason: str) -> None:
        slot.dropped = True
        if slot.inbox is not None:
            await slot.inbox.stop()
        await cancel_and_wait(*slot.tasks, ignore=(Exception,))
        slot.inputs.close()
        slot.commands.close()
        if slot.set_up:
            try:
                await slot.module.teardown()
            except Exception:  # one instance's teardown must not end the host's feeds
                logger.exception("%s: the teardown for key %s failed", self.name, slot.key)
        await slot.out.close()
        if slot.module.sources is not None:
            try:
                await slot.module.sources.close()
            except Exception:  # one instance's sources must not end the host's feeds
                logger.exception("%s: closing the sources for key %s failed", self.name, slot.key)
        logger.info("%s: instance dropped for key %s (%s), %d running", self.name, slot.key, reason, len(self._slots))


async def serve_hosts(hosts: Sequence[ModuleHost]) -> None:
    """Serve every host until cancelled."""
    if hosts:
        await asyncio.gather(*(host.serve() for host in hosts))
