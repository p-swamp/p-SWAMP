# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``ModuleHost``: runs a module, one instance per run key, off the transport.

    topic <app>.<input>,   key k ─▶ the instance for key k ─▶ Module.arun
    topic <app>.<command>, key k ─▶ its command inbox       ─▶ Module.ahandle
    topic <app>.<output>,  key k ◀─ each of its outputs (and ErrorEvents)

The host subscribes to every input of the module. Inputs go to the instance's
queue, which applies the module's overflow policy, and ``serve_module`` reads
them one at a time. A module joining named inputs queues only its trigger: any
other input only replaces the newest of its kind in the join (``observe``), so
a fast stream never backs up behind a slow trigger. Each output of a call is
published on its own topic, under the key the input came with.

An instance is built on the first message for its key, so a per-client run
costs one instance per client, and a shared live run one in total. It is
dropped when its run publishes ``PipelineClosed``, or, if that was lost, after
``idle_seconds`` with nothing for it.

An instance that fails (its ``setup`` raises, say) is logged, reported as an
``ErrorEvent`` under its key, and dropped. The first message for that key
after ``retry_seconds`` builds a new one; what arrives before is ignored.

With the in-memory transport the server runs the hosts itself; with a broker a
worker does (``pswamp_core.worker``). The module cannot tell the difference.

A module that ``reads_gateway`` gets a gateway of its own per instance, built
by the pipeline's factory from the same configuration the server reads.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from pswamp_models.common import ErrorEvent, PipelineClosed

from .command_routing import CommandInbox, concrete_commands
from .keep_up import KeepUpMonitor
from .log import get_logger
from .subscription import Overflow, Subscription
from .transport import Outbox
from .util.tasks import cancel_and_wait, finish
from .util.time import utcnow

if TYPE_CHECKING:
    from collections.abc import AsyncIterable

    from pswamp_models.common import Command

    from .datagateway import DataGateway
    from .modules import Module
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


async def serve_module(module: Module, inputs: Subscription, out: Sink) -> None:
    """Feed ``module`` from ``inputs`` and publish its outputs into ``out``,
    until cancelled or ``inputs`` closes. A failing call, or an output that is
    undeclared or does not fit its envelope, is logged, reported as an
    ``ErrorEvent``, and the next input is read. Falling behind is reported
    per the module's ``keep_up``."""
    if not inputs.models:
        return
    what = f"is not keeping up with {', '.join(model.topic for model in inputs.models)}"
    monitor = KeepUpMonitor(module.name, what, module.keep_up)
    async for message in inputs:
        try:
            monitor.observe(inputs, message, out)
            for output in await module.arun(message):
                out.publish(output)
        except Exception as error:
            logger.exception("module %s failed on %s", module.name, type(message).__name__)
            out.publish(
                ErrorEvent(
                    timestamp=utcnow(),
                    source=module.name,
                    message=f"module {module.name} failed on {type(message).__name__}",
                    detail=f"{type(error).__name__}: {error}",
                )
            )


class _Answering:
    """A module as the command inbox sees a receiver."""

    def __init__(self, module: Module) -> None:
        self.module = module
        self.name = module.name
        self.commands = module.commands

    def validate(self, command: Command) -> None:
        self.module.validate(command)

    async def handle(self, command: Command) -> object:
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
    """One key's module instance, with its queues, outbox and tasks."""

    def __init__(self, key: str, module: Module, transport: Transport, app: str) -> None:
        self.key = key
        self.module = module
        # Queues exist before the module is set up, so nothing arriving
        # meanwhile is lost.
        self.inputs = Subscription(_Local(), module.queued_inputs(), module.overflow, module.maxsize)
        self.commands = Subscription(_Local(), module.commands, Overflow.GROW, 0)
        self.out = Outbox(transport, app=app, key=key)
        self.inbox: CommandInbox | None = None
        self.tasks: list[asyncio.Task] = []
        self.seen = time.monotonic()


class ModuleHost:
    """Runs one instance of a module per run key.

    Args:
        module: The module class, or a factory building a fresh instance.
        transport: The process's transport.
        app: The app whose topics the module is reached on.
        idle_seconds: How long a key may go without a message before its
            instance is dropped, in case its ``PipelineClosed`` never arrives.
        retry_seconds: How long a key is left alone after its instance failed.
        gateway: Builds a gateway for an instance that ``reads_gateway``.
    """

    def __init__(
        self,
        module: type[Module] | Callable[[], Module],
        transport: Transport,
        *,
        app: str,
        idle_seconds: float = DEFAULT_IDLE_SECONDS,
        retry_seconds: float = DEFAULT_RETRY_SECONDS,
        gateway: Callable[[], DataGateway] | None = None,
    ) -> None:
        self._factory = module
        self._gateway = gateway
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
        self._slots: dict[str, _Slot] = {}
        #: The instances that failed, for ``_reap`` to drop.
        self._failed: asyncio.Queue[_Slot] = asyncio.Queue()
        #: Per key whose instance failed: when (monotonic) it may be rebuilt.
        self._retry_at: dict[str, float] = {}

    def keys(self) -> list[str]:
        """The keys with a running instance."""
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

    async def _feed(self, feed: TransportSubscription, queue: str | None) -> None:
        """Hand each message to its key's instance: into ``queue``, or with
        none, straight into the instance's join."""
        with feed:
            async for key, message in feed:
                slot = self._slot(key)
                if slot is None:
                    continue
                slot.seen = time.monotonic()
                if queue is None:
                    slot.module.observe(message)
                else:
                    getattr(slot, queue).offer(message)

    async def _closed(self, feed: TransportSubscription) -> None:
        with feed:
            async for key, closed in feed:
                await self._evict(key, closed.reason)

    def _slot(self, key: str) -> _Slot | None:
        """The key's slot, built if it has none; ``None`` while the key is
        left alone after its instance failed."""
        slot = self._slots.get(key)
        if slot is None:
            if time.monotonic() < self._retry_at.get(key, 0.0):
                return None
            self._retry_at.pop(key, None)
            slot = self._slots[key] = _Slot(key, self._factory(), self.transport, self.app)
            slot.tasks.append(asyncio.create_task(self._run(slot), name=f"{self.name}@{key}"))
        return slot

    async def _run(self, slot: _Slot) -> None:
        """One instance from setup until its ``run`` ends. A failure on the
        way is logged, reported under the key, and handed to ``_reap``."""
        try:
            await self._start(slot)
            await serve_module(slot.module, slot.inputs, slot.out)
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
            self._retry_at[slot.key] = time.monotonic() + self.retry_seconds
            self._failed.put_nowait(slot)

    async def _start(self, slot: _Slot) -> None:
        module = slot.module
        slot.out.start()
        if module.reads_gateway and self._gateway is not None:
            module.gateway = self._gateway()
        await module.setup()
        if module.commands:
            slot.inbox = command_inbox(module, slot.commands, slot.out)
            slot.inbox.start()
        logger.info("%s: instance started for key %s (%d running)", self.name, slot.key, len(self._slots))

    async def _reap(self) -> None:
        """Drop the instances that failed. Here and not in the instance's own
        task, which cannot wait for its own end."""
        while True:
            slot = await self._failed.get()
            if self._slots.get(slot.key) is slot:
                await self._evict(slot.key, "failed")

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
        if slot.inbox is not None:
            await slot.inbox.stop()
        await cancel_and_wait(*slot.tasks, ignore=(Exception,))
        slot.inputs.close()
        slot.commands.close()
        await slot.out.close()
        if slot.module.gateway is not None:
            try:
                await slot.module.gateway.close()
            except Exception:  # one instance's gateway must not end the host's feeds
                logger.exception("%s: closing the gateway for key %s failed", self.name, slot.key)
        logger.info("%s: instance dropped for key %s (%s), %d running", self.name, slot.key, reason, len(self._slots))


async def serve_hosts(hosts: Sequence[ModuleHost]) -> None:
    """Serve every host until cancelled."""
    if hosts:
        await asyncio.gather(*(host.serve() for host in hosts))
