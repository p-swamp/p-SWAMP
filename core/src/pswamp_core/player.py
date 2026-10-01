# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``Player``: paces a run's active source, and owns the controls.

    player = Player(gateway, sink, loop=True)
    await player.start()       # a recording: paused at its start; a live feed: followed from now
    player.status()            # PlayerStatus: mode, source, cursor, speed, what applies

It takes the player commands (``PlayCommand``, ``SeekCommand``, ...) through
``validate`` and ``handle``, like any command receiver.

- **Mode is the active source's kind.** A history is *replayed*: paced in
  real time (times ``speed``), seekable, looping at its end if ``loop``. A
  live source is *followed*: frames go out as they arrive, and no transport
  control applies.
- **Paused, it shows the frame at its cursor.** A seek, a step, a switch to a
  recording and the start all publish the frame there, so a page always has
  one to show.
- **A seek is a new stream**; a stream only moves forward. A seek with an end
  plays that chunk and stops there, paused, without looping.
- **Pacing drops time rather than bursting** when the loop falls behind.
- **A provider failure stops the stream**: paused, ``error`` set in the
  status, and an ``ErrorEvent`` published. Play or seek tries again.
- **With ``follow_live``, a live source is not opened here.** The player of a
  client's run only reports that it is on the live source; the run follows the
  shared live run's topics instead (``pswamp_core.pipeline``).

One task does everything: it reads the stream, paces frames, and applies
commands, which ``handle`` queues for it. So nothing here needs a lock, and a
live feed gone quiet never delays a command.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, ClassVar

from .command_routing import CommandRefused
from .log import get_logger
from .messages.commands import (
    Command,
    PauseCommand,
    PlayCommand,
    PlayerCommand,
    SeekCommand,
    SpeedCommand,
    StepCommand,
    SwitchSourceCommand,
)
from .messages.control import PlayerStatus
from .messages.errors import ErrorEvent
from .util.tasks import cancel_and_wait
from .util.time import utcnow

if TYPE_CHECKING:
    from .datagateway import DataGateway, DataStream, TimeRange
    from .messages.data_model import DataModel
    from .subscription import Sink

__all__ = ["PLAYER_COMMANDS", "Player"]

logger = get_logger("pswamp_core.player")

#: Every command the player handles.
PLAYER_COMMANDS: tuple[type[PlayerCommand], ...] = (
    PlayCommand,
    PauseCommand,
    StepCommand,
    SeekCommand,
    SpeedCommand,
    SwitchSourceCommand,
)

#: The commands that move or pace a replay; none applies to a live source.
_TRANSPORT = (PlayCommand, PauseCommand, StepCommand, SeekCommand, SpeedCommand)

_END = object()


class Player:
    """Paces the gateway's active source. See the module docstring.

    Args:
        gateway: Where the frames come from.
        sink: Where frames, ``PlayerStatus`` and ``ErrorEvent`` go: the run.
        loop: Start a recording over when it ends.
        follow_live: Leave a live source to a shared run: open no stream on it.
    """

    name: ClassVar[str] = "player"
    commands: ClassVar[tuple[type[Command], ...]] = PLAYER_COMMANDS

    def __init__(self, gateway: DataGateway, sink: Sink, *, loop: bool = False, follow_live: bool = False) -> None:
        self._gateway = gateway
        self._sink = sink
        self.loop = loop
        self.follow_live = follow_live
        self.speed = 1.0
        self.paused = True
        self.ended = False
        self.error: str | None = None
        self.cursor: datetime | None = None
        #: The last frame published: the one at the cursor.
        self.last_frame: DataModel | None = None
        self._coverage: TimeRange | None = None
        self._range_end: datetime | None = None
        self._stream: DataStream | None = None
        self._read: asyncio.Task | None = None
        self._held: DataModel | None = None
        self._anchor: tuple[datetime, float] | None = None
        #: Seconds between frames, from the last frame's header.
        self._interval: float | None = None
        self._played_since_open = False
        self._queue: deque[tuple[Command, asyncio.Future]] = deque()
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None

    # -- state ---------------------------------------------------------------------

    @property
    def live(self) -> bool:
        return self._gateway.live

    def status(self) -> PlayerStatus:
        coverage = self._coverage
        return PlayerStatus(
            timestamp=utcnow(),
            mode="live" if self.live else "replay",
            source=self._gateway.source,
            sources=self._gateway.sources,
            cursor=self.cursor,
            speed=self.speed,
            paused=self.paused,
            loop=self.loop,
            ended=self.ended,
            can_seek=not self.live and coverage is not None,
            coverage_start=None if coverage is None else coverage.start,
            coverage_end=None if coverage is None else coverage.end,
            range_end=self._range_end,
            error=self.error,
        )

    # -- lifecycle -----------------------------------------------------------------

    async def start(self) -> None:
        """Open the active source and start the task. Never raises for a
        provider failure: the status says what went wrong."""
        await self._open()
        self.paused = not self.live
        await self._show_if_paused()
        self._task = asyncio.create_task(self._run(), name="player.run")
        self._publish_status()

    async def stop(self) -> None:
        if self._task is not None:
            await cancel_and_wait(self._task, ignore=(Exception,))
            self._task = None
        await self._close()
        while self._queue:
            _, future = self._queue.popleft()
            if not future.done():
                future.set_exception(CommandRefused("the player stopped"))

    # -- commands ------------------------------------------------------------------

    def validate(self, command: Command) -> None:
        """Raise ``CommandRefused`` if ``command`` does not apply now. The
        web API calls this before publishing a command: a refusal is its 409."""
        if isinstance(command, SwitchSourceCommand):
            if command.source not in self._gateway.sources:
                raise CommandRefused(f"no source named {command.source!r}; the sources are {self._gateway.sources}")
            return
        if isinstance(command, _TRANSPORT) and self.live:
            raise CommandRefused(f"{command.name} does not apply to a live source")
        needs_coverage = isinstance(command, SeekCommand) or (isinstance(command, StepCommand) and command.n < 0)
        if needs_coverage and self._coverage is None:
            raise CommandRefused(f"cannot {command.name}: the source reports nothing to seek in")
        if isinstance(command, SeekCommand):
            start, end = self._coverage.start, self._coverage.end
            if start + timedelta(seconds=command.offset_s) >= end:
                raise CommandRefused(f"offset {command.offset_s}s lies past the end of the recording")

    async def handle(self, command: Command) -> None:
        """Queue ``command`` for the player's task, and wait until it is applied."""
        if self._task is None or self._task.done():
            raise CommandRefused("the player is not running")
        future = asyncio.get_running_loop().create_future()
        self._queue.append((command, future))
        self._wake.set()
        await future

    async def _apply(self, command: Command) -> None:
        self.validate(command)  # again: the state may have changed since it was sent
        if isinstance(command, PlayCommand):
            if self._stream is None:  # ended or failed: start over (at the cursor, if it failed)
                await self._open(self.cursor if self.error else None)
            self.paused = False
        elif isinstance(command, PauseCommand):
            self.paused = True
        elif isinstance(command, SpeedCommand):
            self.speed = command.speed
        elif isinstance(command, StepCommand):
            await self._step(command.n)
        elif isinstance(command, SeekCommand):
            base = self._coverage.start
            end = None if command.end_offset_s is None else base + timedelta(seconds=command.end_offset_s)
            await self._open(base + timedelta(seconds=command.offset_s), end)
            self.paused = self.paused and not command.play
            await self._show_if_paused()
        elif isinstance(command, SwitchSourceCommand):
            self._gateway.switch(command.source)
            await self._open()
            self.paused = not self.live
            await self._show_if_paused()
        self._anchor = None

    async def _step(self, n: int) -> None:
        if n < 0:
            if self.cursor is None or self._interval is None:
                return
            target = max(self.cursor - timedelta(seconds=self._interval * -n), self._coverage.start)
            await self._open(target)
            n = 1
        for _ in range(n):
            frame = await self._take()
            if frame is None:
                return
            self._emit(frame)

    # -- the task ------------------------------------------------------------------

    async def _run(self) -> None:
        while True:
            if self._queue:
                command, future = self._queue.popleft()
                try:
                    await self._apply(command)
                except Exception as error:
                    if not future.done():
                        future.set_exception(error)
                else:
                    if not future.done():
                        future.set_result(None)
                self._publish_status()
                continue
            if self.paused or self._stream is None:
                await self._wait()
                continue
            if self._held is None:
                if not await self._wait(self._reading()):
                    continue  # a command arrived first
                frame = await self._next()
                if frame is None:
                    continue
                self._held = frame
            delay = self._due(self._held)
            if delay > 0 and await self._wait(timeout=delay) is None:
                continue  # a command arrived while pacing; the frame stays held
            self._emit(self._held)
            self._held = None

    async def _wait(self, read: asyncio.Task | None = None, timeout: float | None = None) -> bool | None:
        """Wait for ``read``, a command, or ``timeout``. ``True`` when ``read``
        finished; ``None`` when a command is waiting; ``False`` otherwise."""
        if self._queue:
            return None
        self._wake.clear()
        waiter = asyncio.create_task(self._wake.wait())
        try:
            await asyncio.wait({waiter} | ({read} if read else set()), timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        finally:
            waiter.cancel()
        if self._queue:
            return None
        return read is not None and read.done()

    # -- the stream ----------------------------------------------------------------

    async def _open(self, start: datetime | None = None, end: datetime | None = None) -> None:
        """Close the current stream and open the active source at ``start``
        (default: a recording's start; a live feed's now), up to ``end``."""
        await self._close()
        self.error, self.ended, self.last_frame = None, False, None
        self._anchor, self._played_since_open, self._range_end = None, False, None
        try:
            if self.live:
                self._coverage = None
                self.cursor = None
                if not self.follow_live:
                    self._stream = await self._gateway.consume(utcnow())
                return
            self._coverage = await self._gateway.coverage()
            if self._coverage is None:
                raise LookupError("the source holds nothing")
            start = self._coverage.start if start is None else max(start, self._coverage.start)
            if end is not None and end < self._coverage.end:
                self._range_end = end
            self.cursor = start
            self._stream = await self._gateway.consume(start, end or self._coverage.end)
        except Exception as error:
            self._fail(error)

    async def _close(self) -> None:
        read, self._read = self._read, None
        if read is not None and not read.done():
            await cancel_and_wait(read, ignore=(Exception,))
        stream, self._stream = self._stream, None
        self._held = None
        if stream is not None:
            with contextlib.suppress(Exception):
                await stream.aclose()

    def _reading(self) -> asyncio.Task:
        """The read in flight on the stream, started if there is none."""
        if self._read is None:
            self._read = asyncio.create_task(_read_one(self._stream), name="player.read")
        return self._read

    async def _next(self) -> DataModel | None:
        """The finished read's frame. At the end of the stream, loop or end;
        on a provider failure, fail. ``None`` when there is no frame."""
        read, self._read = self._reading(), None
        try:
            frame = await read
        except Exception as error:
            await self._close()
            self._fail(error)
            return None
        if frame is not _END:
            self._played_since_open = True
            return frame
        if self.live:
            await self._close()
            self._fail(EOFError("the live feed ended"))
        elif self.loop and self._range_end is None and self._played_since_open:
            await self._open()
        else:
            await self._close()
            self.ended, self.paused = True, True
            self._publish_status()
        return None

    async def _take(self) -> DataModel | None:
        """The held frame, or the next one (``None`` at the end)."""
        if self._held is not None:
            frame, self._held = self._held, None
            return frame
        if self._stream is None:
            return None
        return await self._next()

    async def _show_if_paused(self) -> None:
        """Publish the frame at the cursor, so a paused page has one to show."""
        if self.paused and self._stream is not None and not self.live:
            frame = await self._take()
            if frame is not None:
                self._emit(frame)

    # -- pacing and publishing -----------------------------------------------------

    def _due(self, frame: DataModel) -> float:
        """Seconds until ``frame`` is due; 0 when live, or first after a change."""
        if self.live or frame.timestamp is None:
            return 0.0
        now = time.monotonic()
        if self._anchor is None:
            self._anchor = (frame.timestamp, now)
            return 0.0
        anchor_at, anchor_now = self._anchor
        delay = anchor_now + (frame.timestamp - anchor_at).total_seconds() / self.speed - now
        if self._interval is not None and -delay > self._interval / self.speed:
            self._anchor = (frame.timestamp, now)  # more than a frame behind: drop time
            return 0.0
        return delay

    def _emit(self, frame: DataModel) -> None:
        header = getattr(frame, "header", None)
        if header is not None:
            self._interval = 1.0 / header.data_rate
        self.cursor = frame.timestamp
        self.last_frame = frame
        self._sink.publish(frame)

    def _fail(self, error: BaseException) -> None:
        source = self._gateway.source
        self.error = f"{source}: {type(error).__name__}: {error}"
        self.ended, self.paused = True, True
        logger.error("the stream from %s stopped: %s", source, self.error)
        self._sink.publish(
            ErrorEvent(timestamp=utcnow(), source=self.name, message=f"the stream from {source} stopped", detail=self.error)
        )
        self._publish_status()

    def _publish_status(self) -> None:
        self._sink.publish(self.status())


async def _read_one(stream: DataStream) -> DataModel | object:
    """The stream's next record, or ``_END``."""
    try:
        return await stream.__anext__()
    except StopAsyncIteration:
        return _END
