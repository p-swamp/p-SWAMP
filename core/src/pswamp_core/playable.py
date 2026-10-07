# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``Playable``: a history source that can be replayed, paced and sought.

A mixin for a ``SourceModule`` of kind ``history``::

    class SampleReplay(Playable, SourceModule):
        name = "sample-replay"
        kind = "history"
        ...

It carries the pacing and the controls that ``Player`` gives a run's active
source today, so the source *is* its own player, and a live source (which does
not mix it in) simply has no transport controls. The interface a run drives it
by, the same for every playable source:

    await source.start(sink, loop=True, sources=["sample", "live"])
    source.status()                 # PlayerStatus: unchanged shape
    source.validate(command)        # raise CommandRefused if it does not apply now
    await source.handle(command)    # queue it, wait until it is applied
    await source.stop()             # stop pacing; the source itself stays open

``commands`` lists what it answers: ``PlayCommand``, ``PauseCommand``,
``StepCommand``, ``SeekCommand`` and ``SpeedCommand``. (``SwitchSourceCommand``
selects *which* source is active, so it belongs to the run, not to one source.)
``start`` may be called again after ``stop``, as a run does when it switches
back to this source; ``speed`` and ``loop`` carry over, the stream restarts.

- **Replayed**: frames are paced in real time (times ``speed``), seekable,
  looping at the end if ``loop``.
- **Paused, it shows the frame at its cursor.** A seek, a step and the start
  all publish the frame there, so a page always has one to show.
- **A seek is a new stream**; a stream only moves forward. A seek with an end
  plays that chunk and stops there, paused, without looping.
- **Pacing drops time rather than bursting** when the loop falls behind.
- **A provider failure stops the stream**: paused, ``error`` set in the
  status, and an ``ErrorEvent`` published. Play or seek tries again.

Following a shared live run (``follow_live``) is not here: a live source is not
playable, and the run decides what to follow.

One task does everything: it reads the stream, paces frames, and applies
commands, which ``handle`` queues for it. So nothing here needs a lock.

The mixin keeps its state in ``speed``, ``paused``, ``ended``, ``error``,
``cursor``, ``last_frame``, ``loop`` and attributes prefixed ``_pl_``: names a
source class using it should not reuse. It needs from its host class what a
``SourceModule`` has: ``source``, ``kind``, ``aread``, ``acoverage``, and
``_ensure_open``. It reads the source through a ``SourceStream``, so the
frames are guarded and enriched the same way a ``SourceSet`` does.

(``Player`` in ``player.py`` is the same state machine for the data clients
still in use; it goes when the run switches to sources, and this is its
replacement.)
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar

from pswamp_models.common import Command, ErrorEvent
from pswamp_models.player import (
    PauseCommand,
    PlayCommand,
    PlayerStatus,
    SeekCommand,
    SpeedCommand,
    StepCommand,
)

from .command_routing import CommandRefused
from .datagateway.enrich import Enricher
from .datagateway.time_range import TimeRange
from .log import get_logger
from .sources import SourceStream
from .util.tasks import cancel_and_wait
from .util.time import utcnow

if TYPE_CHECKING:
    from pswamp_models.common import DataModel

    from .subscription import Sink

__all__ = ["PLAYBACK_COMMANDS", "Playable"]

logger = get_logger("pswamp_core.playable")

#: The commands a playable source handles.
PLAYBACK_COMMANDS: tuple[type[Command], ...] = (PlayCommand, PauseCommand, StepCommand, SeekCommand, SpeedCommand)

_END = object()


class Playable:
    """Replay controls for a history ``SourceModule``. See the module docstring."""

    commands: ClassVar[tuple[type[Command], ...]] = PLAYBACK_COMMANDS

    #: Start a recording over when it ends.
    loop: bool = False
    speed: float = 1.0
    paused: bool = True
    ended: bool = False
    error: str | None = None
    cursor: datetime | None = None
    #: The last frame published: the one at the cursor.
    last_frame: Any = None

    _pl_task: asyncio.Task | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not cls.__dict__.get("abstract", False) and getattr(cls, "kind", None) != "history":
            raise TypeError(f"{cls.__name__}: only a history source can be Playable, not kind={getattr(cls, 'kind', None)!r}")

    # -- state ---------------------------------------------------------------------

    def status(self) -> PlayerStatus:
        coverage = getattr(self, "_pl_coverage", None)
        return PlayerStatus(
            timestamp=utcnow(),
            mode="replay",
            source=self.source,
            sources=list(getattr(self, "_pl_sources", None) or [self.source]),
            cursor=self.cursor,
            speed=self.speed,
            paused=self.paused,
            loop=self.loop,
            ended=self.ended,
            can_seek=coverage is not None,
            coverage_start=None if coverage is None else coverage.start,
            coverage_end=None if coverage is None else coverage.end,
            range_end=getattr(self, "_pl_range_end", None),
            error=self.error,
        )

    # -- lifecycle -----------------------------------------------------------------

    async def start(
        self, sink: Sink, *, loop: bool = False, enrichers: Sequence[Enricher] = (), sources: Sequence[str] | None = None
    ) -> None:
        """Open the source at its start, paused, and start the task. Never
        raises for a provider failure: the status says what went wrong.

        Args:
            sink: Where frames, ``PlayerStatus`` and ``ErrorEvent`` go: the run.
            loop: Start the recording over when it ends.
            enrichers: Applied to every frame, as a ``SourceSet``'s are.
            sources: The names a status lists as the run's sources (this
                source's own, by default).
        """
        if self._pl_task is not None and not self._pl_task.done():
            raise RuntimeError(f"{self.source} is already playing; stop it first")
        self._pl_sink = sink
        self.loop = loop
        self._pl_enrichers = tuple(enrichers)
        self._pl_sources = list(sources) if sources is not None else [self.source]
        self._pl_coverage: TimeRange | None = None
        self._pl_range_end: datetime | None = None
        self._pl_stream: SourceStream | None = None
        self._pl_read: asyncio.Task | None = None
        self._pl_held: DataModel | None = None
        self._pl_anchor: tuple[datetime, float] | None = None
        #: Seconds between frames, from the last frame's header.
        self._pl_interval: float | None = None
        self._pl_played_since_open = False
        self._pl_queue: deque[tuple[Command, asyncio.Future]] = deque()
        self._pl_wake = asyncio.Event()
        await self._pl_open()
        self.paused = True
        await self._pl_show_if_paused()
        self._pl_task = asyncio.create_task(self._pl_run(), name=f"{self.source}.playback")
        self._pl_publish_status()

    async def stop(self) -> None:
        """Stop pacing and close the stream. The source stays open: its
        ``SourceSet`` (or ``async with``) closes it."""
        if self._pl_task is not None:
            await cancel_and_wait(self._pl_task, ignore=(Exception,))
            self._pl_task = None
        await self._pl_close()
        while self._pl_queue:
            _, future = self._pl_queue.popleft()
            if not future.done():
                future.set_exception(CommandRefused("the player stopped"))

    # -- commands ------------------------------------------------------------------

    def validate(self, command: Command) -> None:
        """Raise ``CommandRefused`` if ``command`` does not apply now. The
        web API calls this before publishing a command: a refusal is its 409."""
        if not isinstance(command, PLAYBACK_COMMANDS):
            raise CommandRefused(f"{command.name} is not a playback command")
        coverage = getattr(self, "_pl_coverage", None)
        needs_coverage = isinstance(command, SeekCommand) or (isinstance(command, StepCommand) and command.n < 0)
        if needs_coverage and coverage is None:
            raise CommandRefused(f"cannot {command.name}: the source reports nothing to seek in")
        if isinstance(command, SeekCommand):
            start, end = coverage.start, coverage.end
            if start + timedelta(seconds=command.offset_s) >= end:
                raise CommandRefused(f"offset {command.offset_s}s lies past the end of the recording")

    async def handle(self, command: Command) -> None:
        """Queue ``command`` for the task, and wait until it is applied."""
        if self._pl_task is None or self._pl_task.done():
            raise CommandRefused("the player is not running")
        future = asyncio.get_running_loop().create_future()
        self._pl_queue.append((command, future))
        self._pl_wake.set()
        await future

    async def _pl_apply(self, command: Command) -> None:
        self.validate(command)  # again: the state may have changed since it was sent
        if isinstance(command, PlayCommand):
            if self._pl_stream is None:  # ended or failed: start over (at the cursor, if it failed)
                await self._pl_open(self.cursor if self.error else None)
            self.paused = False
        elif isinstance(command, PauseCommand):
            self.paused = True
        elif isinstance(command, SpeedCommand):
            self.speed = command.speed
        elif isinstance(command, StepCommand):
            await self._pl_step(command.n)
        elif isinstance(command, SeekCommand):
            base = self._pl_coverage.start
            end = None if command.end_offset_s is None else base + timedelta(seconds=command.end_offset_s)
            await self._pl_open(base + timedelta(seconds=command.offset_s), end)
            self.paused = self.paused and not command.play
            await self._pl_show_if_paused()
        self._pl_anchor = None

    async def _pl_step(self, n: int) -> None:
        if n < 0:
            if self.cursor is None or self._pl_interval is None:
                return
            target = max(self.cursor - timedelta(seconds=self._pl_interval * -n), self._pl_coverage.start)
            await self._pl_open(target)
            n = 1
        for _ in range(n):
            frame = await self._pl_take()
            if frame is None:
                return
            self._pl_emit(frame)

    # -- the task ------------------------------------------------------------------

    async def _pl_run(self) -> None:
        while True:
            if self._pl_queue:
                command, future = self._pl_queue.popleft()
                try:
                    await self._pl_apply(command)
                except Exception as error:
                    if not future.done():
                        future.set_exception(error)
                else:
                    if not future.done():
                        future.set_result(None)
                self._pl_publish_status()
                continue
            if self.paused or self._pl_stream is None:
                await self._pl_wait()
                continue
            if self._pl_held is None:
                if not await self._pl_wait(self._pl_reading()):
                    continue  # a command arrived first
                frame = await self._pl_next()
                if frame is None:
                    continue
                self._pl_held = frame
            delay = self._pl_due(self._pl_held)
            if delay > 0 and await self._pl_wait(timeout=delay) is None:
                continue  # a command arrived while pacing; the frame stays held
            self._pl_emit(self._pl_held)
            self._pl_held = None

    async def _pl_wait(self, read: asyncio.Task | None = None, timeout: float | None = None) -> bool | None:
        """Wait for ``read``, a command, or ``timeout``. ``True`` when ``read``
        finished; ``None`` when a command is waiting; ``False`` otherwise."""
        if self._pl_queue:
            return None
        self._pl_wake.clear()
        waiter = asyncio.create_task(self._pl_wake.wait())
        try:
            await asyncio.wait({waiter} | ({read} if read else set()), timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        finally:
            waiter.cancel()
        if self._pl_queue:
            return None
        return read is not None and read.done()

    # -- the stream ----------------------------------------------------------------

    async def _pl_open(self, start: datetime | None = None, end: datetime | None = None) -> None:
        """Close the current stream and open the source at ``start`` (default:
        the recording's start), up to ``end``."""
        await self._pl_close()
        self.error, self.ended, self.last_frame = None, False, None
        self._pl_anchor, self._pl_played_since_open, self._pl_range_end = None, False, None
        try:
            await self._ensure_open()
            self._pl_coverage = await self.acoverage()
            if self._pl_coverage is None:
                raise LookupError("the source holds nothing")
            start = self._pl_coverage.start if start is None else max(start, self._pl_coverage.start)
            if end is not None and end < self._pl_coverage.end:
                self._pl_range_end = end
            self.cursor = start
            self._pl_stream = SourceStream(
                self, TimeRange(start, end or self._pl_coverage.end), self._pl_enrichers
            )
        except Exception as error:
            self._pl_fail(error)

    async def _pl_close(self) -> None:
        read, self._pl_read = getattr(self, "_pl_read", None), None
        if read is not None and not read.done():
            await cancel_and_wait(read, ignore=(Exception,))
        stream, self._pl_stream = getattr(self, "_pl_stream", None), None
        self._pl_held = None
        if stream is not None:
            with contextlib.suppress(Exception):
                await stream.aclose()

    def _pl_reading(self) -> asyncio.Task:
        """The read in flight on the stream, started if there is none."""
        if self._pl_read is None:
            self._pl_read = asyncio.create_task(_read_one(self._pl_stream), name=f"{self.source}.read")
        return self._pl_read

    async def _pl_next(self) -> DataModel | None:
        """The finished read's frame. At the end of the stream, loop or end;
        on a provider failure, fail. ``None`` when there is no frame."""
        read, self._pl_read = self._pl_reading(), None
        try:
            frame = await read
        except Exception as error:
            await self._pl_close()
            self._pl_fail(error)
            return None
        if frame is not _END:
            self._pl_played_since_open = True
            return frame
        if self.loop and self._pl_range_end is None and self._pl_played_since_open:
            await self._pl_open()
        else:
            await self._pl_close()
            self.ended, self.paused = True, True
            self._pl_publish_status()
        return None

    async def _pl_take(self) -> DataModel | None:
        """The held frame, or the next one (``None`` at the end)."""
        if self._pl_held is not None:
            frame, self._pl_held = self._pl_held, None
            return frame
        if self._pl_stream is None:
            return None
        return await self._pl_next()

    async def _pl_show_if_paused(self) -> None:
        """Publish the frame at the cursor, so a paused page has one to show."""
        if self.paused and self._pl_stream is not None:
            frame = await self._pl_take()
            if frame is not None:
                self._pl_emit(frame)

    # -- pacing and publishing -----------------------------------------------------

    def _pl_due(self, frame: DataModel) -> float:
        """Seconds until ``frame`` is due; 0 for the first after a change."""
        if frame.timestamp is None:
            return 0.0
        now = time.monotonic()
        if self._pl_anchor is None:
            self._pl_anchor = (frame.timestamp, now)
            return 0.0
        anchor_at, anchor_now = self._pl_anchor
        delay = anchor_now + (frame.timestamp - anchor_at).total_seconds() / self.speed - now
        if self._pl_interval is not None and -delay > self._pl_interval / self.speed:
            self._pl_anchor = (frame.timestamp, now)  # more than a frame behind: drop time
            return 0.0
        return delay

    def _pl_emit(self, frame: DataModel) -> None:
        header = getattr(frame, "header", None)
        if header is not None:
            self._pl_interval = 1.0 / header.data_rate
        self.cursor = frame.timestamp
        self.last_frame = frame
        self._pl_sink.publish(frame)

    def _pl_fail(self, error: BaseException) -> None:
        self.error = f"{self.source}: {type(error).__name__}: {error}"
        self.ended, self.paused = True, True
        logger.error("the stream from %s stopped: %s", self.source, self.error)
        self._pl_sink.publish(
            ErrorEvent(
                timestamp=utcnow(), source="player", message=f"the stream from {self.source} stopped", detail=self.error
            )
        )
        self._pl_publish_status()

    def _pl_publish_status(self) -> None:
        self._pl_sink.publish(self.status())


async def _read_one(stream: SourceStream) -> DataModel | object:
    """The stream's next record, or ``_END``."""
    try:
        return await stream.__anext__()
    except StopAsyncIteration:
        return _END
