# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``Playable``: a history source that can be replayed, paced and sought.

A mixin for a ``SourceModule`` of kind ``history``::

    class SampleReplay(Playable, SourceModule):
        name = "sample-replay"
        kind = "history"
        ...

It carries the pacing and the controls of a run's active source, so the source
*is* its own player, and a live source (which does not mix it in) simply has no
transport controls. The run's ``ActiveSource`` router (``pswamp_core.active_source``)
sends the playback commands to it. The interface a run drives it
by, the same for every playable source:

    await source.start(sink, loop=True, sources=["sample", "live"])
    source.status()                 # PlayerStatus: unchanged shape
    source.validate(command)        # raise CommandRefused if it does not apply now
    await source.ahandle(command)   # queue it, wait until it is applied
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
  plays that chunk and stops there, paused, without looping. ``streams``
  counts them: the start, a seek, a step back, a loop to the start and a play
  after the end each open one, and a run resets its modules on each.
- **Pacing drops time rather than bursting** when the loop falls behind.
- **A gap is crossed at once, and reported.** When the next frame lies more
  than ``GAP`` seconds (``{SOURCE}_GAP``, default 1; at least two frame
  intervals) past the cursor, it is due now, not after the gap, and an
  ``ErrorEvent`` says where the data stops and starts again. A seek that lands
  in a gap reports it the same way, and so does a chunk with no data at all.
  Every gap is logged; the tray gets at most one report per
  ``GAP_REPORT_EVERY_S`` (the first of each stream always), with the gaps in
  between counted into the next.
- **A provider failure stops the stream**: paused, ``error`` set in the
  status, and an ``ErrorEvent`` published. Play or seek tries again.

Following a shared live run (``follow_live``) is not here: a live source is not
playable, and the run decides what to follow.

One task does everything: it reads the stream, paces frames, and applies
commands, which ``ahandle`` queues for it. So nothing here needs a lock.

The mixin keeps its state in ``speed``, ``paused``, ``ended``, ``error``,
``cursor``, ``last_frame``, ``loop``, ``streams`` and attributes prefixed ``_pl_``: names a
source class using it should not reuse. It adds the ``GAP`` setting to the
class's ``env_settings``. It needs from its host class what a
``SourceModule`` has: ``source``, ``kind``, ``settings``, ``aread``, ``acoverage``, and
``_ensure_open``. It reads the source through a ``SourceStream``, so the
frames are guarded and enriched the same way a ``SourceSet`` does.
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
from .enrich import Enricher
from .time_range import TimeRange
from .log import get_logger
from .settings import EnvSetting
from .sources import SourceStream
from .util.tasks import cancel_and_wait
from .util.time import utcnow

if TYPE_CHECKING:
    from pswamp_models.common import DataModel

    from .subscription import Sink

__all__ = ["GAP_REPORT_EVERY_S", "GAP_SETTING", "PLAYBACK_COMMANDS", "Playable"]

logger = get_logger("pswamp_core.playable")

#: The commands a playable source handles.
PLAYBACK_COMMANDS: tuple[type[Command], ...] = (PlayCommand, PauseCommand, StepCommand, SeekCommand, SpeedCommand)

#: The setting every playable source gets: how long a stretch without frames
#: is a gap, crossed at once and reported.
GAP_SETTING = EnvSetting("GAP", "Seconds without frames that are a gap: crossed at once, and reported", default="1", kind="seconds")

#: At most one gap report on the tray per this many seconds of wall clock.
GAP_REPORT_EVERY_S = 5.0

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
    #: How many streams it has opened (see the module docstring).
    streams: int = 0

    _pl_task: asyncio.Task | None = None
    _pl_interval: float | None = None
    #: When the last gap went to the tray (``time.monotonic``), and how many since.
    _pl_gap_reported: float | None = None
    _pl_gaps_held: int = 0

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not cls.__dict__.get("abstract", False) and getattr(cls, "kind", None) != "history":
            raise TypeError(f"{cls.__name__}: only a history source can be Playable, not kind={getattr(cls, 'kind', None)!r}")
        settings = tuple(getattr(cls, "env_settings", ()))
        if not any(setting.setting == GAP_SETTING.setting for setting in settings):
            cls.env_settings = (*settings, GAP_SETTING)

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
        #: The grid ids already reported as not this run's (once each per run).
        self._pl_grids_reported: set[str] = set()
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
            # Before the start is fine: the seek lands on the first frame.
            if coverage.end is not None and command.at >= coverage.end:
                raise CommandRefused(f"{_utc(command.at)} UTC lies past the end of the recording, {_utc(coverage.end)} UTC")
            if command.until is not None and command.until <= coverage.start:
                raise CommandRefused(f"the chunk ends at {_utc(command.until)} UTC, before the recording starts")

    async def ahandle(self, command: Command) -> None:
        """Queue ``command`` for the task, and wait until it is applied. It is
        ``Module.ahandle``: the answer goes out through the sink, so it returns
        nothing, and it needs the loop that ran ``start``."""
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
            await self._pl_open(command.at, command.until)
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
        self.streams += 1
        self.error, self.ended, self.last_frame = None, False, None
        self._pl_anchor, self._pl_played_since_open, self._pl_range_end = None, False, None
        self._pl_gap_reported, self._pl_gaps_held = None, 0  # the first gap of a stream always shows
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
        if not self._pl_played_since_open and self.cursor is not None:  # a range with no data at all
            self._pl_report_gap(self.cursor, self._pl_range_end or self._pl_coverage.end, empty=True)
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
        """Seconds until ``frame`` is due; 0 for the first after a change, and
        for the first after a gap."""
        if frame.timestamp is None:
            return 0.0
        now = time.monotonic()
        if self._pl_anchor is None or self._pl_gap(frame) is not None:
            self._pl_anchor = (frame.timestamp, now)
            return 0.0
        anchor_at, anchor_now = self._pl_anchor
        delay = anchor_now + (frame.timestamp - anchor_at).total_seconds() / self.speed - now
        if self._pl_interval is not None and -delay > self._pl_interval / self.speed:
            self._pl_anchor = (frame.timestamp, now)  # more than a frame behind: drop time
            return 0.0
        return delay

    def _pl_emit(self, frame: DataModel) -> None:
        if self._pl_gap(frame) is not None:
            self._pl_report_gap(self.cursor, frame.timestamp)
        header = getattr(frame, "header", None)
        if header is not None:
            self._pl_interval = 1.0 / header.data_rate
            self._pl_check_grid(header.cimReferenceId)
        self.cursor = frame.timestamp
        self.last_frame = frame
        self._pl_sink.publish(frame)

    def _pl_check_grid(self, recorded: str | None) -> None:
        """Report, once per id, a frame tied to another grid than this run's. Enrichment leaves a
        reference a frame already has, so a recording keeps the grid it was made under; the run's
        own (an enricher's ``reference``) is what it is compared with, once it has one."""
        if recorded is None or recorded in self._pl_grids_reported:
            return
        current = next((ref for e in self._pl_enrichers if (ref := getattr(e, "reference", None))), None)
        if current is None:
            return
        self._pl_grids_reported.add(recorded)
        if recorded != current:
            logger.warning("%s: frames are tied to grid %s, this run to %s", self.source, recorded, current)
            self._pl_sink.publish(
                ErrorEvent(
                    timestamp=utcnow(),
                    source="player",
                    message=f"{self.source} was recorded under another grid than this run's",
                    detail=f"its frames are tied to grid {recorded}; this run is tied to grid {current}. Playback goes on.",
                )
            )

    # -- gaps ----------------------------------------------------------------------

    def _pl_gap(self, frame: DataModel) -> timedelta | None:
        """How far ``frame`` lies past the cursor, when that is a gap: more than
        ``GAP``, and more than two frame intervals."""
        if self.cursor is None or frame.timestamp is None:
            return None
        jump = frame.timestamp - self.cursor
        threshold = max(self.settings.gap.total_seconds(), 2 * (self._pl_interval or 0.0))
        return jump if jump.total_seconds() > threshold else None

    def _pl_report_gap(self, start: datetime, end: datetime, *, empty: bool = False) -> None:
        """Log a gap, and report it on the tray unless one was reported less
        than ``GAP_REPORT_EVERY_S`` ago; then it is counted into the next."""
        where = f"{_utc(start)} to {_utc(end)} UTC"
        message = (
            f"no data from {self.source} in the range asked for"
            if empty
            else f"no data from {self.source} for {_span(end - start)}"
        )
        logger.warning("%s: %s", message, where)
        now = time.monotonic()
        if self._pl_gap_reported is not None and now - self._pl_gap_reported < GAP_REPORT_EVERY_S:
            self._pl_gaps_held += 1
            return
        held, self._pl_gaps_held, self._pl_gap_reported = self._pl_gaps_held, 0, now
        detail = where if empty else f"{where}; playback went straight on to the next frame"
        if held:
            detail += f" (and {held} more {'gap' if held == 1 else 'gaps'} since the last report)"
        self._pl_sink.publish(ErrorEvent(timestamp=utcnow(), source="player", message=message, detail=detail))

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


def _utc(moment: datetime) -> str:
    """``2026-03-14 13:05:00.040``: to the millisecond."""
    return moment.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _span(span: timedelta) -> str:
    """``2.50 s`` under a minute; ``2 d 19 h 55 min`` above."""
    seconds = span.total_seconds()
    if seconds < 60:
        return f"{seconds:.2f} s"
    days, rest = divmod(round(seconds), 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    return " ".join(f"{value} {unit}" for value, unit in ((days, "d"), (hours, "h"), (minutes, "min"), (secs, "s")) if value)


async def _read_one(stream: SourceStream) -> DataModel | object:
    """The stream's next record, or ``_END``."""
    try:
        return await stream.__anext__()
    except StopAsyncIteration:
        return _END
