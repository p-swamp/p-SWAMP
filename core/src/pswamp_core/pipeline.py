# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""Pipelines: what an app's data flows through, declared once, run per key.

A **``Pipeline``** is the declaration: the app's name (the namespace of its
topics), its sources (a ``SourceSet`` factory) and its modules. An app declares it
as data, in ``pipelines/<app>.toml``, which ``Pipeline.load`` reads (see
``pswamp_core.pipeline_config``)::

    PIPELINE = Pipeline.load("pipelines/pmu-test-streamer.toml")

A test may declare one in code: ``Pipeline("app", sources, modules=(FrameStatsModule,))``.

A **``PipelineRun``** is one running instance under one key: a set of sources,
a router over them (``ActiveSource``) and an outbox. It publishes under
``<key>#<run id>.<stream>`` (``pswamp_core.keys``): a run id of its own, so a
module host gives a new run of the same client fresh instances, and a stream
number that goes up each time the stream starts over (a seek, a step back, a
loop, a switch), so a host resets its instances in order with the frames. A
result from before the stream started over is dropped, unless it answers a
command. A module instance that starts (a rebuilt one, after a worker
restart) is sent the run's sticky settings again (``Command.sticky``). It
publishes the active
source's frames to the modules and listens for their results. The modules themselves run in module hosts,
wherever the deployment puts them (``Pipeline.hosts``, ``pswamp_core.worker``);
the run and the hosts meet only on the transport::

    DATA DOWN    active source → run.publish → topic <app>.pmu.frame, key → module (hosted)
                 run.latest ← topic <app>.<result>, key ← module
    COMMANDS UP  run.dispatch(cmd) → topic <app>.<command>, key → router → active source | module

The run keeps the newest message of each class (``latest``) and wakes readers
on every change (``changes()``). That is what the web API builds its socket
message from: however much arrived meanwhile, it sends one message.

**Live is shared.** A recording is replayed per client, each with its own
cursor. A live source has one run of its own, keyed ``live.<source>``, started
with the app and running until shutdown (``start_live_runs``), so its modules
run once however many people watch. A client's run switched to a live source
opens no stream: it *follows* the live run, taking that key's frames and
results off the transport into its own ``latest``, and its status: ``status()``
carries the live run's error while its feed is down. A command for a module that
reads the stream is refused meanwhile: that module's instance runs under the
live run's key, for every viewer, so its settings are not one viewer's.

A **``PipelineRegistry``** keeps one run per key: it builds a run on first
``acquire``, keeps it through a reload, evicts it when idle or, at the cap,
the least recently used one nobody is watching.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
from collections.abc import AsyncIterator, Callable, Collection
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, TypeVar

from pswamp_models.common import Command, ErrorEvent, ModuleStarted, PipelineClosed
from pswamp_models.player import PlayerStatus, SwitchSourceCommand

from .active_source import ROUTER_COMMANDS, ActiveSource
from .command_routing import CommandInbox, CommandRefused, NoReceiver, concrete_commands
from .host import DEFAULT_IDLE_SECONDS, ModuleHost
from .keep_up import KeepUp
from .keys import StreamKey, next_run_id, run_of
from .log import get_logger
from .sources import SourceModule
from .subscription import Overflow
from .transport import Outbox
from .util.tasks import cancel_and_wait, finish
from .util.time import utcnow

if TYPE_CHECKING:
    from pswamp_models.common import DataModel

    from .modules import Module
    from .sources import SourceSet
    from .transport import Transport, TransportSubscription

__all__ = [
    "CapacityError",
    "NewestByClass",
    "Pipeline",
    "PipelineRegistry",
    "PipelineRun",
    "live_key",
    "start_live_runs",
]

logger = get_logger("pswamp_core.pipeline")

#: How long a run waits at start for its topics to be received.
_READY_TIMEOUT_S = 20.0

#: How often a shared live run repeats its status while its feed is down, so
#: that a viewer who comes to it later hears why there is nothing.
_STATUS_EVERY_S = 2.0

M = TypeVar("M", bound="DataModel")


@dataclass(frozen=True)
class Pipeline:
    """An app's pipeline, declared once.

    Attributes:
        app: The app's name: its topics are ``<app>.<topic>``.
        sources: Builds a fresh ``SourceSet`` over the app's sources.
        modules: The module classes, hosted wherever the transport says.

    Raises ``ValueError`` when two receivers (the player, a module) take the
    same command class: a command class is an address. Also when a module
    sends a command (lists it in its ``outputs``) that nothing in the pipeline
    takes, and when two classes of the pipeline have the same topic, as two of
    the same name do: a topic carries one class. And, when ``source_models``
    is given, when a module reads a class nothing in the pipeline produces.
    """

    app: str
    sources: Callable[[], SourceSet]
    modules: tuple[type[Module], ...] = ()
    #: What the sources serve. When given (``Pipeline.load`` always gives it),
    #: every class a module reads must have a producer in the pipeline.
    source_models: tuple[type[DataModel], ...] | None = None

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> Pipeline:
        """The pipeline declared in the file at ``path`` (``pipelines/<app>.toml``).
        See ``pswamp_core.pipeline_config``."""
        from .pipeline_config import load_pipeline

        return load_pipeline(path)

    def __post_init__(self) -> None:
        for module in self.modules:
            if issubclass(module, SourceModule):
                raise ValueError(f"{self.app}: {module.__name__} is a source: list it under [[sources]], not modules")
        taken: dict[type[Command], str] = {command: "the player" for command in ROUTER_COMMANDS}
        for module in self.modules:
            for command in concrete_commands(module.__name__, module.commands):
                if command in taken:
                    raise ValueError(f"{self.app}: {module.__name__} and {taken[command]} both take {command.__name__}")
                taken[command] = module.__name__
        for module in self.modules:
            for model in module.outputs:
                if issubclass(model, Command) and model not in taken:
                    raise ValueError(f"{self.app}: {module.__name__} sends {model.__name__}, which nothing in the pipeline takes")
        on_topic: dict[str, type[DataModel]] = {}
        for model in (ErrorEvent, PipelineClosed, ModuleStarted, *taken, *self.inputs, *self.outputs):
            other = on_topic.setdefault(model.topic, model)
            if other is not model:
                raise ValueError(
                    f"{self.app}: {other.__module__}.{other.__qualname__} and {model.__module__}.{model.__qualname__} "
                    f"are both on topic {model.topic}; rename one, or give it a topic of its own (topic: ClassVar[str])"
                )
        if self.source_models is not None:
            produced = {*self.source_models, *self.outputs, PlayerStatus, ErrorEvent, PipelineClosed}
            for module in self.modules:
                for model in module.input_models():
                    if model not in produced:
                        raise ValueError(
                            f"{self.app}: {module.name} reads {model.__name__}, which nothing in the pipeline produces "
                            f"(the sources serve {_names(self.source_models)}; the modules emit {_names(self.outputs)})"
                        )

    @property
    def inputs(self) -> frozenset[type[DataModel]]:
        """What the modules read: what a run publishes to them."""
        return frozenset(model for m in self.modules for model in m.input_models())

    @property
    def outputs(self) -> tuple[type[DataModel], ...]:
        """Everything the modules publish, commands they send included."""
        return tuple(dict.fromkeys(model for m in self.modules for model in m.outputs))

    @property
    def results(self) -> tuple[type[DataModel], ...]:
        """What the modules publish other than commands: what a run listens
        for. A command a module sends reaches its receiver on its own topic."""
        return tuple(model for model in self.outputs if not issubclass(model, Command))

    def live_sources(self) -> list[str]:
        """The sources that are live feeds, each of which gets a shared run."""
        sources = self.sources()
        return [name for name in sources.sources if sources.kind(name) == "live"]

    def module_for(self, command: type[Command]) -> type[Module] | None:
        return next((m for m in self.modules if command in m.commands), None)

    def hosts(
        self, transport: Transport, *, only: Collection[str] | None = None, idle_seconds: float = DEFAULT_IDLE_SECONDS
    ) -> list[ModuleHost]:
        """One host per module, or per module named in ``only``."""
        return [
            ModuleHost(module, transport, app=self.app, idle_seconds=idle_seconds, sources=self.sources)
            for module in self.modules
            if only is None or module.name in only
        ]


def _names(models: Collection[type]) -> str:
    return ", ".join(model.__name__ for model in models) or "nothing"


def live_key(source: str) -> str:
    """The key of the shared run of a live source."""
    return f"live.{source}"


class NewestByClass:
    """The newest message of each class seen. (Not a module's join, which is
    ``pswamp_core.inputs.Latest``.)"""

    def __init__(self) -> None:
        self._by_class: dict[type[DataModel], DataModel] = {}

    def remember(self, message: DataModel) -> None:
        self._by_class[type(message)] = message

    def get(self, model: type[M]) -> M | None:
        return self._by_class.get(model)  # type: ignore[return-value]

    def forget(self, *models: type[DataModel]) -> None:
        for model in models:
            self._by_class.pop(model, None)


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
        loop: A recording starts over at its end.
        live_source: Make this the shared run of that live source, instead of
            a client's run.
        on_error: Called with the run's key and an ``ErrorEvent`` for what the
            run could not put on the transport: a command not delivered within
            the outbox's deadline, or an error report itself. The web API hands
            it to the tray directly, since the tray is fed through the transport.
    """

    def __init__(
        self,
        key: str,
        pipeline: Pipeline,
        transport: Transport,
        *,
        loop: bool = True,
        live_source: str | None = None,
        on_error: Callable[[str, ErrorEvent], None] | None = None,
    ) -> None:
        self.key = key
        #: This run's id: a module host builds fresh instances for a new one.
        self.run_id = next_run_id()
        self._stream = 0
        #: The router's ``stream_mark`` when the stream number last went up.
        self._mark: tuple[int, int] | None = None
        self.pipeline = pipeline
        self.transport = transport
        self._on_error = on_error
        self.sources = pipeline.sources()
        self.shared = live_source is not None
        if live_source is not None:
            self.sources.switch(live_source)
        self.latest = NewestByClass()
        self.outbox = Outbox(
            transport,
            app=pipeline.app,
            key=str(self.stream_key),
            keep_up=KeepUp(),
            label=f"the server-side publisher for {key}",
            on_undelivered=self._undelivered,
        )
        # A client's run leaves live sources to their shared runs.
        self.router = ActiveSource(self.sources, self, loop=loop, follow_live=not self.shared)
        #: The frame at the cursor: the active source's, or the live run's while following it.
        self.frame: DataModel | None = None
        self._following: TransportSubscription | None = None
        #: The shared live run's newest status, while following it.
        self._followed_status: PlayerStatus | None = None
        self._waiters: set[asyncio.Event] = set()
        #: The last command of each sticky class sent to a module: sent again
        #: to an instance of it that starts.
        self._sticky: dict[type[Command], Command] = {}
        self._inbox: CommandInbox | None = None
        self._subscriptions: list[TransportSubscription] = []
        self._tasks: list[asyncio.Task] = []
        self._started = False

    # -- the router's sink, and the view ----------------------------------------------

    def publish(self, message: DataModel) -> None:
        """What the active source publishes: remembered here, and put on the transport
        when a module reads it, it is an error, or it is a shared run's frame or
        status."""
        mark = self.router.stream_mark
        if mark != self._mark:
            self._mark = mark
            self._stream += 1
            self.outbox.key = str(self.stream_key)
        if isinstance(message, PlayerStatus):
            self._follow(message)
        elif message is self.router.last_frame:
            self.frame = message
        self._remember(message)
        shared = self.shared and (message is self.router.last_frame or isinstance(message, PlayerStatus))
        if shared or type(message) in self.pipeline.inputs or isinstance(message, ErrorEvent):
            self.outbox.publish(message)

    def status(self) -> PlayerStatus:
        """The player's status as this run's viewer sees it: its router's,
        with the shared live run's error and end while following one."""
        own = self.router.status()
        followed = self._followed_status
        if self._following is None or followed is None:
            return own
        return own.model_copy(update={"error": followed.error, "ended": followed.ended})

    def changes(self) -> Changes:
        """Wake-ups on every change; close it (or use ``with``) when done."""
        return Changes(self._waiters)

    @property
    def stream_key(self) -> StreamKey:
        """What this run publishes under now."""
        return StreamKey(self.key, self.run_id, self._stream)

    @property
    def following(self) -> str | None:
        """The key of the shared live run this run follows, if any."""
        return None if self._following is None else self._following.key

    def _remember(self, message: DataModel) -> None:
        self.latest.remember(message)
        for event in self._waiters:
            event.set()

    def _follow(self, status: PlayerStatus) -> None:
        """Follow the shared run of the live source the router is on; stop
        following when it leaves it."""
        key = live_key(status.source) if status.mode == "live" and not self.shared else None
        following = None if self._following is None else self._following.key
        if following == key:
            return
        self._unfollow()
        # Results from the other side of the switch (this run's own, or the
        # live run's) are not about what comes next.
        self.latest.forget(*self.pipeline.results)
        if key is None:
            return
        model = self.sources.active.model
        self.frame = None
        self._following = self.transport.subscribe(
            model, PlayerStatus, *self.pipeline.results, app=self.pipeline.app, key=key
        )
        self._tasks.append(asyncio.create_task(self._receive_followed(self._following, model), name=f"{self.key}.follow"))

    def _unfollow(self) -> None:
        if self._following is not None:
            self._following.close()  # ends its _receive task
            self._following = None
        self._followed_status = None

    def _undelivered(self, message: DataModel, error: Exception | None) -> None:
        """What the outbox gave up on, to ``on_error``: a command or an error
        report is someone's business; a ``PipelineClosed`` is nobody's."""
        if self._on_error is None or isinstance(message, PipelineClosed):
            return
        if isinstance(message, ErrorEvent):
            self._on_error(self.key, message)
            return
        what = message.name if isinstance(message, Command) else type(message).__name__
        cause = f"{type(error).__name__}: {error}" if error is not None else "it waited in the queue past its deadline"
        self._on_error(
            self.key,
            ErrorEvent(
                timestamp=utcnow(),
                source="server",
                message=f"{what} was not delivered within {self.outbox.deadline:g} s, so it was not applied",
                detail=cause,
                request_id=getattr(message, "request_id", None),
            ),
        )

    # -- commands -------------------------------------------------------------------

    def dispatch(self, command: Command) -> None:
        """Publish ``command`` on its topic, under this run's key.

        A player command (a switch or a playback command) is validated first,
        by the router, so a refusal raises ``CommandRefused`` here (the web
        API's 409) and nothing is published. A
        module command is published as it is: the module validates it where
        it runs, and a refusal comes back as an ``ErrorEvent``. While the run
        follows a shared live run, a command for a module that reads the
        stream raises ``CommandRefused``: its instance for this view is the
        live run's. A command nothing takes raises ``NoReceiver``.
        """
        if type(command) in ROUTER_COMMANDS:
            self.router.validate(command)
        else:
            module = self.pipeline.module_for(type(command))
            if module is None:
                raise NoReceiver(f"{self.pipeline.app} has no receiver for {type(command).__name__}")
            if self._following is not None and module.input_models():
                raise CommandRefused(
                    f"{module.name} reads the shared live run {self._following.key}, so its settings are not "
                    f"per viewer: switch to a recording to change them"
                )
            if command.sticky:
                self._sticky[type(command)] = command
        self.outbox.publish(command)

    # -- lifecycle ------------------------------------------------------------------

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        app, key, subscribe = self.pipeline.app, self.key, self.transport.subscribe
        await self.transport.open()
        # The router takes its commands off their topics, so a module can
        # command it exactly as the web API does.
        commands = subscribe(*ROUTER_COMMANDS, app=app, key=key, overflow=Overflow.GROW)
        self._subscriptions.append(commands)
        if self.pipeline.results:
            results = subscribe(*self.pipeline.results, app=app, key=key)
            self._subscriptions.append(results)
            self._tasks.append(asyncio.create_task(self._receive(results), name=f"{app}@{key}.results"))
        if any(command.sticky for module in self.pipeline.modules for command in module.commands):
            started = subscribe(ModuleStarted, app=app, key=key, overflow=Overflow.GROW)
            self._subscriptions.append(started)
            self._tasks.append(asyncio.create_task(self._resend_settings(started), name=f"{app}@{key}.started"))
        # A command dispatched once start() returns must find its topic received.
        for subscription in self._subscriptions:
            await subscription.ready(_READY_TIMEOUT_S)
        self.outbox.start()
        await self.router.start()
        if self.shared:
            self._tasks.append(asyncio.create_task(self._repeat_status(), name=f"{key}.status"))
        # A switch stops a command still waiting on the source it leaves (one that hangs).
        self._inbox = CommandInbox(
            (command async for key, command in commands if self._ours(key)),
            self.router,
            self,
            preempt=(SwitchSourceCommand,),
        )
        self._inbox.start()

    async def stop(self, reason: str = "stopped") -> None:
        if self._started:
            self._started = False
            await finish(self._teardown(reason))  # to the end, even if cancelled meanwhile

    async def _teardown(self, reason: str) -> None:
        if self._inbox is not None:
            await self._inbox.stop()
        await self.router.stop()
        self._unfollow()
        await cancel_and_wait(*self._tasks)
        for subscription in self._subscriptions:
            subscription.close()
        self.outbox.publish(PipelineClosed(timestamp=utcnow(), reason=reason))
        await self.outbox.close()
        await self.sources.close()

    def _ours(self, key: str) -> bool:
        """``key`` is this run's, not an earlier run's of the same key (a
        plain key, as a test publishes by hand, counts as ours)."""
        return StreamKey.parse(key).run_id in (0, self.run_id)

    async def _receive(self, results: TransportSubscription) -> None:
        async for key, result in results:
            if not self._ours(key):
                continue
            stream = StreamKey.parse(key).stream
            if 0 < stream < self._stream and getattr(result, "request_id", None) is None:
                continue  # from before the stream started over, and nobody asked for it
            self._remember(result)

    async def _resend_settings(self, started: TransportSubscription) -> None:
        """Send a module instance that starts the sticky settings this run
        has sent its module, stamped now: a rebuilt instance has lost them,
        and a command stamped long ago would be refused as late."""
        async for key, message in started:
            if not self._ours(key):
                continue
            for cls, command in list(self._sticky.items()):
                module = self.pipeline.module_for(cls)
                if module is not None and module.name == message.module:
                    logger.info("%s: %s started; sending it %s again", self.key, module.name, command.name)
                    self.outbox.publish(command.model_copy(update={"timestamp": utcnow()}))

    async def _receive_followed(self, messages: TransportSubscription, frames: type[DataModel]) -> None:
        async for _, message in messages:
            if messages is not self._following:
                return  # unfollowed: what is still queued belongs to the live run
            if isinstance(message, PlayerStatus):
                self._followed_status = message  # read through status(); this run's own stays in latest
                for event in self._waiters:
                    event.set()
                continue
            if type(message) is frames:
                self.frame = message
            self._remember(message)

    async def _repeat_status(self) -> None:
        """A shared run's status, again every ``_STATUS_EVERY_S`` while its
        feed is down: a viewer who switches to it later hears it too."""
        while True:
            await asyncio.sleep(_STATUS_EVERY_S)
            status = self.router.status()
            if status.error is not None:
                self.outbox.publish(status)


async def start_live_runs(
    pipeline: Pipeline, transport: Transport, *, on_error: Callable[[str, ErrorEvent], None] | None = None
) -> list[PipelineRun]:
    """One started shared run per live source of ``pipeline``."""
    runs = [
        PipelineRun(live_key(source), pipeline, transport, live_source=source, on_error=on_error)
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

    def watching(self, key: str) -> list[str]:
        """The keys of the runs that show what is published under ``key`` (a
        run's key, or any key it publishes under): the run itself, or every run
        following the shared live run ``key``."""
        run = run_of(key)
        if run in self._entries:
            return [run]
        return [k for k, entry in self._entries.items() if entry.run.following == run]

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
