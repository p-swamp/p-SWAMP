# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``ModuleHost``: runs a module, one instance per run key, off the transport.

    topic <app>.<input>,   key k ─▶ the instance for key k ─▶ Module.process
    topic <app>.<command>, key k ─▶ its command inbox       ─▶ Module.handle
    topic <app>.<result>,  key k ◀─ what the instance publishes (and ErrorEvents)

An instance is built on the first message for its key, so a per-client run
costs one instance per client, and a shared live run one in total. It is
dropped when its run publishes ``PipelineClosed``, or, if that was lost, after
``idle_seconds`` with nothing for it.

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

from .command_routing import CommandInbox, concrete_commands
from .log import get_logger
from .messages.control import PipelineClosed
from .subscription import Overflow, Subscription
from .transport import Outbox
from .util.tasks import cancel_and_wait, finish

if TYPE_CHECKING:
    from .datagateway import DataGateway
    from .modules import Module
    from .transport import Transport, TransportSubscription

__all__ = ["DEFAULT_IDLE_SECONDS", "ModuleHost", "serve_hosts"]

logger = get_logger("pswamp_core.host")

DEFAULT_IDLE_SECONDS = 300.0

#: The shared feed of one topic, across keys: only a hand-off to each key's
#: own queue, which applies the module's overflow policy.
_FEED_MAXSIZE = 1024


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
        inputs = (module.input_model,) if module.input_model is not None else ()
        self.inputs = Subscription(_Local(), inputs, module.overflow, module.maxsize)
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
        gateway: Builds a gateway for an instance that ``reads_gateway``.
    """

    def __init__(
        self,
        module: type[Module] | Callable[[], Module],
        transport: Transport,
        *,
        app: str,
        idle_seconds: float = DEFAULT_IDLE_SECONDS,
        gateway: Callable[[], DataGateway] | None = None,
    ) -> None:
        self._factory = module
        self._gateway = gateway
        self.transport = transport
        self.app = app
        self.idle_seconds = idle_seconds
        template = module()
        self.name = template.name
        self.input_model = template.input_model
        self.output_model = template.output_model
        self.commands = concrete_commands(type(template).__name__, template.commands)
        self._slots: dict[str, _Slot] = {}

    def keys(self) -> list[str]:
        """The keys with a running instance."""
        return list(self._slots)

    async def serve(self) -> None:
        """Consume the module's topics and run instances until cancelled."""
        await self.transport.open()
        subscribe = self.transport.subscribe
        feeds = [self._closed(subscribe(PipelineClosed, app=self.app, overflow=Overflow.GROW))]
        if self.input_model is not None:
            feeds.append(self._feed(subscribe(self.input_model, app=self.app, maxsize=_FEED_MAXSIZE), "inputs"))
        if self.commands:
            feeds.append(self._feed(subscribe(*self.commands, app=self.app, overflow=Overflow.GROW), "commands"))
        tasks = [asyncio.create_task(feed, name=f"{self.name}.host") for feed in feeds]
        tasks.append(asyncio.create_task(self._sweep(), name=f"{self.name}.host.sweep"))
        logger.info(
            "hosting %s for %s: reads %s, publishes %s, commands %s, over %s",
            self.name, self.app, self.input_model.topic if self.input_model else "nothing",
            self.output_model.topic, [c.topic for c in self.commands] or "none", self.transport.name,
        )
        try:
            await asyncio.gather(*tasks)
        finally:
            await cancel_and_wait(*tasks, ignore=(Exception,))
            for key in list(self._slots):
                await self._evict(key, "shutdown")

    async def _feed(self, feed: TransportSubscription, queue: str) -> None:
        with feed:
            async for key, message in feed:
                slot = self._slot(key)
                slot.seen = time.monotonic()
                getattr(slot, queue).offer(message)

    async def _closed(self, feed: TransportSubscription) -> None:
        with feed:
            async for key, closed in feed:
                await self._evict(key, closed.reason)

    def _slot(self, key: str) -> _Slot:
        slot = self._slots.get(key)
        if slot is None:
            slot = self._slots[key] = _Slot(key, self._factory(), self.transport, self.app)
            slot.tasks.append(asyncio.create_task(self._start(slot), name=f"{self.name}@{key}.start"))
        return slot

    async def _start(self, slot: _Slot) -> None:
        module = slot.module
        slot.out.start()
        if module.reads_gateway and self._gateway is not None:
            module.gateway = self._gateway()
        await module.setup(slot.out)
        if module.commands:
            slot.inbox = module.command_inbox(slot.commands, slot.out)
            slot.inbox.start()
        slot.tasks.append(asyncio.create_task(module.run(slot.inputs, slot.out), name=f"{self.name}@{slot.key}.run"))
        logger.info("%s: instance started for key %s (%d running)", self.name, slot.key, len(self._slots))

    async def _sweep(self) -> None:
        interval = max(0.05, min(self.idle_seconds / 2, 5.0))
        while True:
            await asyncio.sleep(interval)
            cutoff = time.monotonic() - self.idle_seconds
            for key in [k for k, s in self._slots.items() if s.seen < cutoff]:
                await self._evict(key, "idle")

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
            await slot.module.gateway.close()
        logger.info("%s: instance dropped for key %s (%s), %d running", self.name, slot.key, reason, len(self._slots))


async def serve_hosts(hosts: Sequence[ModuleHost]) -> None:
    """Serve every host until cancelled."""
    if hosts:
        await asyncio.gather(*(host.serve() for host in hosts))
