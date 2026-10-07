# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``ActiveSource``: a run's router over its sources.

    router = ActiveSource(sources, sink, loop=True)   # sources: a SourceSet
    await router.start()      # opens the active source: a recording paused at its start,
                              # a live feed followed from now
    router.status()           # PlayerStatus: mode, source, cursor, speed, what applies

A run drives exactly one source at a time (the ``SourceSet``'s active one), and
this is the receiver of the commands that steer it, like any command receiver
(``validate`` and ``handle``, see ``pswamp_core.command_routing``):

- ``SwitchSourceCommand`` makes another source active: the one that was is
  stopped, the new one is started.
- The playback commands (``PlayCommand``, ``PauseCommand``, ``StepCommand``,
  ``SeekCommand``, ``SpeedCommand``) go to the active source, when it is
  ``Playable`` (``pswamp_core.playable``): that source *is* its own player, and
  the router only routes. A source that is not playable has no transport
  controls, and the router refuses them: ``<command> does not apply to a live
  source``.
- A source that is not playable is **pumped**: its stream is read from now (a
  live feed) or from the start (a history that is not playable), and frames go
  out as they arrive, unpaced. Its status is ``mode="live"`` for a live feed,
  with no coverage, no cursor control and nothing to seek.
- With ``follow_live``, a live source is not opened here: the router of a
  client's run only reports that it is on the live source, and the run follows
  the shared live run's topics instead (``pswamp_core.pipeline``).

``speed`` and ``loop`` belong to the run, not to a source: a speed set on one
recording carries to the next one switched to, as the single player of old did.

The router publishes into its sink (the run): the frames and ``PlayerStatus``
of a pumped source, an ``ErrorEvent`` when its stream fails, and, through the
playable source, the same for a recording. It is named ``player`` in error
reports, which is what a page and the error tray know it by.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any, ClassVar

from pswamp_models.common import Command, ErrorEvent
from pswamp_models.player import PlayerCommand, PlayerStatus, SpeedCommand, SwitchSourceCommand

from .command_routing import CommandRefused
from .log import get_logger
from .playable import PLAYBACK_COMMANDS, Playable
from .util.tasks import cancel_and_wait
from .util.time import utcnow

if TYPE_CHECKING:
    from datetime import datetime

    from .sources import SourceSet, SourceStream
    from .subscription import Sink

__all__ = ["ROUTER_COMMANDS", "ActiveSource"]

logger = get_logger("pswamp_core.active_source")

#: Every command the router receives: the playback commands, and the switch.
ROUTER_COMMANDS: tuple[type[PlayerCommand], ...] = (*PLAYBACK_COMMANDS, SwitchSourceCommand)  # type: ignore[assignment]


class ActiveSource:
    """Routes a run's commands to its active source. See the module docstring.

    Args:
        sources: The run's sources; its active one is what this drives.
        sink: Where frames, ``PlayerStatus`` and ``ErrorEvent`` go: the run.
        loop: Start a recording over when it ends.
        follow_live: Leave a live source to a shared run: open no stream on it.
    """

    name: ClassVar[str] = "player"
    commands: ClassVar[tuple[type[Command], ...]] = ROUTER_COMMANDS

    def __init__(self, sources: SourceSet, sink: Sink, *, loop: bool = False, follow_live: bool = False) -> None:
        self._sources = sources
        self._sink = sink
        self.loop = loop
        self.follow_live = follow_live
        self.speed = 1.0
        # The state of a pumped source; a playable one keeps its own.
        self.paused = True
        self.ended = False
        self.error: str | None = None
        self.cursor: datetime | None = None
        self._last_frame: Any = None
        self._playable: Playable | None = None
        self._stream: SourceStream | None = None
        self._pump: asyncio.Task | None = None
        self._started = False

    # -- state ---------------------------------------------------------------------

    @property
    def last_frame(self) -> Any:
        """The last frame published: the one at the cursor."""
        return self._playable.last_frame if self._playable is not None else self._last_frame

    def status(self) -> PlayerStatus:
        if self._playable is not None:
            return self._playable.status()
        return PlayerStatus(
            timestamp=utcnow(),
            mode="live" if self._sources.live else "replay",
            source=self._sources.source,
            sources=self._sources.sources,
            cursor=self.cursor,
            speed=self.speed,
            paused=self.paused,
            loop=self.loop,
            ended=self.ended,
            can_seek=False,
            coverage_start=None,
            coverage_end=None,
            range_end=None,
            error=self.error,
        )

    # -- lifecycle -----------------------------------------------------------------

    async def start(self) -> None:
        """Start the active source. Never raises for a provider failure: the
        status says what went wrong."""
        self._started = True
        await self._activate()

    async def stop(self) -> None:
        if self._started:
            self._started = False
            await self._stop_active()

    # -- commands ------------------------------------------------------------------

    def validate(self, command: Command) -> None:
        """Raise ``CommandRefused`` if ``command`` does not apply now. The
        web API calls this before publishing a command: a refusal is its 409."""
        if isinstance(command, SwitchSourceCommand):
            if command.source not in self._sources.sources:
                raise CommandRefused(f"no source named {command.source!r}; the sources are {self._sources.sources}")
            return
        if not isinstance(command, PLAYBACK_COMMANDS):
            raise CommandRefused(f"{command.name} is not a player command")
        if self._playable is None:
            if self._sources.live:
                raise CommandRefused(f"{command.name} does not apply to a live source")
            raise CommandRefused(f"{command.name} does not apply: {self._sources.source} is not playable")
        self._playable.validate(command)

    async def handle(self, command: Command) -> None:
        """Apply ``command``: a switch here, a playback command in the active
        source, waiting until it is applied."""
        if not self._started:
            raise CommandRefused("the player is not running")
        self.validate(command)  # again: the state may have changed since it was sent
        if isinstance(command, SwitchSourceCommand):
            await self._stop_active()
            self._sources.switch(command.source)
            await self._activate()
            return
        assert self._playable is not None  # validate refused otherwise
        await self._playable.handle(command)
        if isinstance(command, SpeedCommand):
            self.speed = command.speed

    # -- the active source -----------------------------------------------------------

    async def _activate(self) -> None:
        """Start the source the set has active, and publish where it is."""
        source = self._sources.active
        if isinstance(source, Playable):
            self._playable = source
            source.speed = self.speed
            # Opens at the start, paused, and publishes the frame there and the status.
            await source.start(
                self._sink, loop=self.loop, enrichers=self._sources.enrichers, sources=self._sources.sources
            )
            return
        self._playable = None
        self.error, self.ended, self.cursor, self._last_frame = None, False, None, None
        self.paused = False
        if not (source.kind == "live" and self.follow_live):
            try:
                self._stream = await self._sources.consume(utcnow() if source.kind == "live" else None)
                self._pump = asyncio.create_task(self._run_pump(self._stream, source.kind == "live"), name="player.pump")
            except Exception as error:
                self._fail(error)
                return
        self._publish_status()

    async def _stop_active(self) -> None:
        """Stop the source that is playing; the set closes the sources themselves."""
        if self._playable is not None:
            await self._playable.stop()
        pump, self._pump = self._pump, None
        if pump is not None:
            await cancel_and_wait(pump, ignore=(Exception,))
        stream, self._stream = self._stream, None
        if stream is not None:
            with contextlib.suppress(Exception):
                await stream.aclose()

    async def _run_pump(self, stream: SourceStream, live: bool) -> None:
        """Publish a source's frames as they arrive, until it ends or fails."""
        try:
            async for frame in stream:
                self.cursor = frame.timestamp
                self._last_frame = frame
                self._sink.publish(frame)
        except Exception as error:
            self._fail(error)
            return
        if live:
            self._fail(EOFError("the live feed ended"))
        else:
            self.ended, self.paused = True, True
            self._publish_status()

    def _fail(self, error: BaseException) -> None:
        source = self._sources.source
        self.error = f"{source}: {type(error).__name__}: {error}"
        self.ended, self.paused = True, True
        logger.error("the stream from %s stopped: %s", source, self.error)
        self._sink.publish(
            ErrorEvent(timestamp=utcnow(), source=self.name, message=f"the stream from {source} stopped", detail=self.error)
        )
        self._publish_status()

    def _publish_status(self) -> None:
        self._sink.publish(self.status())
