# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""Pipelines: what an app's data flows through, declared once, run per key.

A **``Pipeline``** is the declaration: the app's name (the namespace of its
topics), its sources (a gateway factory) and its modules::

    PIPELINE = Pipeline("pmu-test-streamer", gateway, modules=(FrameStatsModule,))

A **``PipelineRun``** is one running instance under one key: a gateway, a
player and an outbox. It publishes the player's frames to the modules and
listens for their results. The modules themselves run in module hosts,
wherever the deployment puts them (``Pipeline.hosts``, ``pswamp_core.worker``);
the run and the hosts meet only on the transport::

    DATA DOWN    gateway → player → run.publish → topic <app>.pmu.frame, key → module (hosted)
                 run.latest ← topic <app>.<result>, key ← module
    COMMANDS UP  run.dispatch(cmd) → topic <app>.<command>, key → player | module

The run keeps the newest message of each class (``latest``) and wakes readers
on every change (``changes()``). That is what the edge builds its socket
message from: however much arrived meanwhile, it sends one message.

**Live is shared.** A recording is replayed per client, each with its own
cursor. A live source has one run of its own, keyed ``live.<source>``, started
with the app and running until shutdown (``start_live_runs``), so its modules
run once however many people watch. A client's run switched to a live source
opens no stream: it *follows* the live run, taking that key's frames and
results off the transport into its own ``latest``.

A **``PipelineRegistry``** keeps one run per key: it builds a run on first
``acquire``, keeps it through a reload, evicts it when idle or, at the cap,
the least recently used one nobody is watching.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Callable, Collection
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, TypeVar

from .command_routing import CommandInbox, NoReceiver, concrete_commands
from .host import DEFAULT_IDLE_SECONDS, ModuleHost
from .log import get_logger
from .messages.commands import Command
from .messages.control import PipelineClosed, PlayerStatus
from .messages.errors import ErrorEvent
from .player import PLAYER_COMMANDS, Player
from .subscription import Overflow
from .transport import Outbox
from .util.tasks import cancel_and_wait, finish
from .util.time import utcnow

if TYPE_CHECKING:
    from .datagateway import DataGateway
    from .messages.data_model import DataModel
    from .messages.results import ResultEnvelope
    from .modules import Module
    from .transport import Transport, TransportSubscription

__all__ = [
    "CapacityError",
    "Latest",
    "Pipeline",
    "PipelineRegistry",
    "PipelineRun",
    "live_key",
    "start_live_runs",
]

logger = get_logger("pswamp_core.pipeline")

#: How long a run waits at start for its topics to be received.
_READY_TIMEOUT_S = 20.0

M = TypeVar("M", bound="DataModel")


@dataclass(frozen=True)
class Pipeline:
    """An app's pipeline, declared once.

    Attributes:
        app: The app's name: its topics are ``<app>.<topic>``.
        gateway: Builds a fresh gateway over the app's sources.
        modules: The module classes, hosted wherever the transport says.

    Raises ``ValueError`` when two receivers (the player, a module) take the
    same command class: a command class is an address.
    """

    app: str
    gateway: Callable[[], DataGateway]
    modules: tuple[type[Module], ...] = ()

    def __post_init__(self) -> None:
        taken: dict[type[Command], str] = {command: "the player" for command in PLAYER_COMMANDS}
        for module in self.modules:
            for command in concrete_commands(module.__name__, module.commands):
                if command in taken:
                    raise ValueError(f"{self.app}: {module.__name__} and {taken[command]} both take {command.__name__}")
                taken[command] = module.__name__

    @property
    def inputs(self) -> frozenset[type[DataModel]]:
        """What the modules read: what a run publishes to them."""
        return frozenset(m.input_model for m in self.modules if m.input_model is not None)

    @property
    def results(self) -> tuple[type[ResultEnvelope], ...]:
        """What the modules publish: what a run listens for."""
        return tuple(dict.fromkeys(m.output_model for m in self.modules))

    def live_sources(self) -> list[str]:
        """The sources that are live feeds, each of which gets a shared run."""
        gateway = self.gateway()
        return [name for name in gateway.sources if gateway.kind(name) == "live"]

    def module_for(self, command: type[Command]) -> type[Module] | None:
        return next((m for m in self.modules if command in m.commands), None)

    def hosts(
        self, transport: Transport, *, only: Collection[str] | None = None, idle_seconds: float = DEFAULT_IDLE_SECONDS
    ) -> list[ModuleHost]:
        """One host per module, or per module named in ``only``."""
        return [
            ModuleHost(module, transport, app=self.app, idle_seconds=idle_seconds, gateway=self.gateway)
            for module in self.modules
            if only is None or module.name in only
        ]


def live_key(source: str) -> str:
    """The key of the shared run of a live source."""
    return f"live.{source}"


class Latest:
    """The newest message of each class seen."""

    def __init__(self) -> None:
        self._by_class: dict[type[DataModel], DataModel] = {}

    def remember(self, message: DataModel) -> None:
        self._by_class[type(message)] = message

    def get(self, model: type[M]) -> M | None:
        return self._by_class.get(model)  # type: ignore[return-value]


class Changes:
    """Wake-ups for one reader. Each step of ``async for`` means "something
    changed since you last looked"; many changes while the reader was busy are
    one wake-up."""

    def __init__(self, waiters: set[asyncio.Event]) -> None:
        self._waiters = waiters
        self._event = asyncio.Event()
        waiters.add(self._event)

    def __aiter__(self) -> Changes:
        return self

    async def __anext__(self) -> None:
        await self._event.wait()
        self._event.clear()

    def close(self) -> None:
        self._waiters.discard(self._event)

    def __enter__(self) -> Changes:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class PipelineRun:
    """One running pipeline under one key. See the module docstring.

    Args:
        key: What the run is isolated by: a client id, for a replay.
        pipeline: What it is made of.
        transport: The process's transport.
        loop: The player starts a recording over at its end.
        live_source: Make this the shared run of that live source, instead of
            a client's run.
    """

    def __init__(
        self, key: str, pipeline: Pipeline, transport: Transport, *, loop: bool = True, live_source: str | None = None
    ) -> None:
        self.key = key
        self.pipeline = pipeline
        self.transport = transport
        self.gateway = pipeline.gateway()
        self.shared = live_source is not None
        if live_source is not None:
            self.gateway.switch(live_source)
        self.latest = Latest()
        self.outbox = Outbox(transport, app=pipeline.app, key=key)
        # A client's run leaves live sources to their shared runs.
        self.player = Player(self.gateway, self, loop=loop, follow_live=not self.shared)
        #: The frame at the cursor: the player's, or the live run's while following it.
        self.frame: DataModel | None = None
        self._following: TransportSubscription | None = None
        self._waiters: set[asyncio.Event] = set()
        self._inbox: CommandInbox | None = None
        self._subscriptions: list[TransportSubscription] = []
        self._tasks: list[asyncio.Task] = []
        self._started = False

    # -- the player's sink, and the view ----------------------------------------------

    def publish(self, message: DataModel) -> None:
        """What the player publishes: remembered here, and put on the transport
        when a module reads it, it is an error, or it is a shared run's frame."""
        if isinstance(message, PlayerStatus):
            self._follow(message)
        elif message is self.player.last_frame:
            self.frame = message
        self._remember(message)
        frame = self.shared and message is self.player.last_frame
        if frame or type(message) in self.pipeline.inputs or isinstance(message, ErrorEvent):
            self.outbox.publish(message)

    def changes(self) -> Changes:
        """Wake-ups on every change; close it (or use ``with``) when done."""
        return Changes(self._waiters)

    def _remember(self, message: DataModel) -> None:
        self.latest.remember(message)
        for event in self._waiters:
            event.set()

    def _follow(self, status: PlayerStatus) -> None:
        """Follow the shared run of the live source the player is on; stop
        following when it leaves it."""
        key = live_key(status.source) if status.mode == "live" and not self.shared else None
        if self._following is not None and self._following.key == key:
            return
        self._unfollow()
        if key is None:
            return
        model = self.gateway.active.model
        self.frame = None
        self._following = self.transport.subscribe(model, *self.pipeline.results, app=self.pipeline.app, key=key)
        self._tasks.append(asyncio.create_task(self._receive_followed(self._following, model), name=f"{self.key}.follow"))

    def _unfollow(self) -> None:
        if self._following is not None:
            self._following.close()  # ends its _receive task
            self._following = None

    # -- commands -------------------------------------------------------------------

    def dispatch(self, command: Command) -> None:
        """Publish ``command`` on its topic, under this run's key.

        A player command is validated first, so a refusal raises
        ``CommandRefused`` here (the edge's 409) and nothing is published. A
        module command is published as it is: the module validates it where
        it runs, and a refusal comes back as an ``ErrorEvent``. A command
        nothing takes raises ``NoReceiver``.
        """
        if type(command) in PLAYER_COMMANDS:
            self.player.validate(command)
        elif self.pipeline.module_for(type(command)) is None:
            raise NoReceiver(f"{self.pipeline.app} has no receiver for {type(command).__name__}")
        self.outbox.publish(command)

    # -- lifecycle ------------------------------------------------------------------

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        app, key, subscribe = self.pipeline.app, self.key, self.transport.subscribe
        await self.transport.open()
        # The player takes its commands off their topics, so a module can
        # command it exactly as the edge does.
        commands = subscribe(*PLAYER_COMMANDS, app=app, key=key, overflow=Overflow.GROW)
        self._subscriptions.append(commands)
        if self.pipeline.results:
            results = subscribe(*self.pipeline.results, app=app, key=key)
            self._subscriptions.append(results)
            self._tasks.append(asyncio.create_task(self._receive(results), name=f"{app}@{key}.results"))
        # A command dispatched once start() returns must find its topic received.
        for subscription in self._subscriptions:
            await subscription.ready(_READY_TIMEOUT_S)
        self.outbox.start()
        await self.player.start()
        self._inbox = CommandInbox((command async for _, command in commands), self.player, self)
        self._inbox.start()

    async def stop(self, reason: str = "stopped") -> None:
        if self._started:
            self._started = False
            await finish(self._teardown(reason))  # to the end, even if cancelled meanwhile

    async def _teardown(self, reason: str) -> None:
        if self._inbox is not None:
            await self._inbox.stop()
        await self.player.stop()
        self._unfollow()
        await cancel_and_wait(*self._tasks)
        for subscription in self._subscriptions:
            subscription.close()
        self.outbox.publish(PipelineClosed(timestamp=utcnow(), reason=reason))
        await self.outbox.close()
        await self.gateway.close()

    async def _receive(self, results: TransportSubscription) -> None:
        async for _, result in results:
            self._remember(result)

    async def _receive_followed(self, messages: TransportSubscription, frames: type[DataModel]) -> None:
        async for _, message in messages:
            if messages is not self._following:
                return  # unfollowed: what is still queued belongs to the live run
            if type(message) is frames:
                self.frame = message
            self._remember(message)


async def start_live_runs(pipeline: Pipeline, transport: Transport) -> list[PipelineRun]:
    """One started shared run per live source of ``pipeline``."""
    runs = [
        PipelineRun(live_key(source), pipeline, transport, live_source=source)
        for source in pipeline.live_sources()
    ]
    for run in runs:
        await run.start()
        logger.info("shared live run started for %s", run.key)
    return runs


class CapacityError(RuntimeError):
    """Every slot holds a run someone is still watching."""


R = TypeVar("R", bound=PipelineRun)


class _Entry(Generic[R]):
    def __init__(self, run: R) -> None:
        self.run = run
        self.sockets = 0
        self.last_used = time.monotonic()
        self.evict_task: asyncio.Task | None = None


class PipelineRegistry(Generic[R]):
    """Builds, caps and evicts runs, one per key.

    - **One run per key, however many sockets.** A per-key lock brackets the
      build, so simultaneous first connects of one client build one run.
    - **A run outlives its last socket by ``idle_seconds``**, so a reload
      rejoins it.
    - **Never more than ``max_runs``, even mid-build.** At the cap a new key
      evicts the least recently used run nobody is watching; if all are
      watched, ``CapacityError``.
    """

    def __init__(self, factory: Callable[[str], R], *, max_runs: int = 8, idle_seconds: float = 300.0) -> None:
        self._factory = factory
        self.max_runs = max_runs
        self.idle_seconds = idle_seconds
        self._entries: dict[str, _Entry[R]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        # acquire() calls in flight per key, counted before the key's lock is
        # taken; the lock is reclaimed only when this is zero.
        self._acquiring: dict[str, int] = {}
        # Runs past the capacity check but not yet in _entries.
        self._pending = 0

    @property
    def live(self) -> int:
        return len(self._entries)

    def keys(self) -> list[str]:
        return list(self._entries)

    def watchers(self, key: str) -> int:
        entry = self._entries.get(key)
        return 0 if entry is None else entry.sockets

    def peek(self, key: str) -> R | None:
        """The key's run if it has one. Never builds: what a command uses."""
        entry = self._entries.get(key)
        return None if entry is None else entry.run

    @contextlib.asynccontextmanager
    async def session(self, key: str) -> AsyncIterator[R]:
        """Hold a key's run for the life of one connection."""
        run = await self.acquire(key)
        try:
            yield run
        finally:
            self.release(key)

    async def acquire(self, key: str) -> R:
        self._acquiring[key] = self._acquiring.get(key, 0) + 1
        try:
            async with self._locks.setdefault(key, asyncio.Lock()):
                entry = self._entries.get(key)
                if entry is not None:
                    if entry.evict_task is not None:
                        entry.evict_task.cancel()
                        entry.evict_task = None
                    entry.sockets += 1
                    entry.last_used = time.monotonic()
                    return entry.run
                await self._make_room()
                self._pending += 1
                try:
                    run = self._factory(key)
                    try:
                        await run.start()
                    except BaseException:
                        with contextlib.suppress(Exception):
                            await run.stop()
                        raise
                    entry = self._entries[key] = _Entry(run)
                    entry.sockets = 1
                finally:
                    self._pending -= 1
                logger.info("run started for %s (%d/%d)", key, self.live, self.max_runs)
                return run
        finally:
            self._acquiring[key] -= 1
            self._drop_lock_if_unused(key)

    def release(self, key: str) -> None:
        entry = self._entries.get(key)
        if entry is None:
            return
        entry.sockets = max(0, entry.sockets - 1)
        entry.last_used = time.monotonic()
        if entry.sockets == 0 and entry.evict_task is None:
            entry.evict_task = asyncio.create_task(self._evict_when_idle(key))

    async def stop_all(self) -> None:
        """Stop every run, on shutdown."""
        entries = list(self._entries.values())
        self._entries.clear()
        self._locks.clear()
        for entry in entries:
            if entry.evict_task is not None:
                entry.evict_task.cancel()
        await asyncio.gather(*(entry.run.stop("shutdown") for entry in entries), return_exceptions=True)

    async def _make_room(self) -> None:
        """Evict at the cap. Never waits on the victim's lock, so no deadlock;
        ``stop`` is idempotent, so racing the victim's idle eviction is harmless."""
        while self.live + self._pending >= self.max_runs:
            idle = [key for key, entry in self._entries.items() if entry.sockets == 0]
            if not idle:
                raise CapacityError(f"all {self.max_runs} runs are in use")
            await self._evict(min(idle, key=lambda k: self._entries[k].last_used), "capacity")

    async def _evict_when_idle(self, key: str) -> None:
        try:
            await asyncio.sleep(self.idle_seconds)
        except asyncio.CancelledError:
            return
        lock = self._locks.get(key)
        if lock is None:
            return
        async with lock:
            entry = self._entries.get(key)
            if entry is not None and entry.sockets == 0:
                await self._evict(key, "idle")

    async def _evict(self, key: str, reason: str) -> None:
        entry = self._entries.pop(key, None)
        self._drop_lock_if_unused(key)
        if entry is not None:
            await entry.run.stop(reason)
            logger.info("run evicted for %s (%s), %d/%d", key, reason, self.live, self.max_runs)

    def _drop_lock_if_unused(self, key: str) -> None:
        if self._acquiring.get(key, 0) <= 0:
            self._acquiring.pop(key, None)
            if key not in self._entries:
                self._locks.pop(key, None)
