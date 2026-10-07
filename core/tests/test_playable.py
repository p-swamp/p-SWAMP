"""``Playable``: paced replay, the controls, and failures. ``test_player.py``'s
cases, against a playable source. (What the run decides rather than the source,
switching to a live feed and the live refusals, stays out.)"""

from __future__ import annotations

import asyncio
import time

import pytest
from support import ListSource, Recorder, at, frame

from pswamp_core.command_routing import CommandRefused
from pswamp_core.datagateway import CimReferenceEnricher
from pswamp_core.playable import PLAYBACK_COMMANDS, Playable
from pswamp_core.sources import SourceModule
from pswamp_models.common import ErrorEvent
from pswamp_models.player import (
    PauseCommand,
    PlayCommand,
    PlayerStatus,
    SeekCommand,
    SpeedCommand,
    StepCommand,
    SwitchSourceCommand,
)
from pswamp_models.pmu import PmuFrame


def frames(out: Recorder) -> list:
    return [f.timestamp for f in out.of(PmuFrame)]


async def running(source, *, loop=False, speed=None, **start) -> tuple[Playable, Recorder]:
    out = Recorder()
    await source.start(out, loop=loop, **start)
    if speed is not None:
        await command(source, SpeedCommand(speed=speed))
    return source, out


async def command(player: Playable, cmd) -> None:
    player.validate(cmd)
    await player.handle(cmd)


async def until(condition, timeout: float = 5.0) -> None:
    async def poll():
        while not condition():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(poll(), timeout)


class Failing(ListSource):
    """Fails after ``after`` frames."""

    name = "failing-list-source"

    def __init__(self, after: int) -> None:
        super().__init__("flaky")
        self.after = after

    def read(self, start=None, end=None):
        for count, record in enumerate(super().read(start, end)):
            if count == self.after:
                raise ConnectionError("store went away")
            yield record


class Unreachable(ListSource):
    name = "unreachable-list-source"

    def coverage(self):
        raise ConnectionError("no route to host")


class Thready(ListSource):
    """Reads in a thread, as a source waiting on a file would."""

    name = "thready-list-source"
    blocking = True


def test_a_live_source_cannot_be_playable():
    with pytest.raises(TypeError, match="history"):

        class Wrong(Playable, SourceModule):
            name = "wrong"
            kind = "live"

            def read(self, start=None, end=None):
                yield from ()


def test_a_playable_answers_the_transport_commands_only():
    assert set(ListSource.commands) == set(PLAYBACK_COMMANDS)
    assert set(PLAYBACK_COMMANDS) == {PlayCommand, PauseCommand, StepCommand, SeekCommand, SpeedCommand}
    with pytest.raises(CommandRefused, match="not a playback command"):
        ListSource().validate(SwitchSourceCommand(source="x"))


async def test_a_recording_starts_paused_showing_its_first_frame():
    player, out = await running(ListSource())
    status = player.status()
    assert (status.mode, status.paused, status.can_seek, status.source) == ("replay", True, True, "list")
    assert status.sources == ["list"]
    assert (status.coverage_start, status.cursor) == (at(0), at(0))
    assert frames(out) == [at(0)]
    assert out.of(PlayerStatus)  # the opening status is published too
    await player.stop()


async def test_the_status_lists_the_run_s_sources():
    player, _ = await running(ListSource(), sources=["list", "live"])
    assert player.status().sources == ["list", "live"]
    await player.stop()


async def test_play_paces_frames_in_order_and_pause_stops_without_skipping():
    player, out = await running(ListSource(), speed=10)  # 20 frames at 20 Hz: 0.1 s, 5 ms apart
    began = time.perf_counter()
    await command(player, PlayCommand())
    await until(lambda: len(frames(out)) >= 11)  # 10 gaps after the first: 0.05 s when paced
    # Paced, not a burst (a burst of 10 frames takes well under a millisecond).
    # Pacing is on time.monotonic() and asyncio's loop clock, whose tick on
    # Windows is ~15.6 ms: the anchor can read up to one tick early and a sleep
    # can wake up to one tick early, so allow two ticks of slack below 80% of
    # the paced time. Elsewhere the tick is ~1 ns and this is 0.04 s.
    tick = time.get_clock_info("monotonic").resolution
    assert time.perf_counter() - began >= 0.04 - 2 * tick
    await command(player, PauseCommand())
    paused_at = len(frames(out))
    await asyncio.sleep(0.05)
    assert len(frames(out)) == paused_at
    await command(player, PlayCommand())
    await until(lambda: len(frames(out)) >= 20)
    assert frames(out)[:20] == [at(i / 20) for i in range(20)]
    await player.stop()


async def test_the_end_loops_or_ends_paused():
    looping, out = await running(ListSource(frames=[frame(i / 20) for i in range(3)]), loop=True, speed=10)
    await command(looping, PlayCommand())
    await until(lambda: len(frames(out)) >= 7)
    assert frames(out)[:7] == [at(0), at(0.05), at(0.1), at(0), at(0.05), at(0.1), at(0)]
    await looping.stop()
    once, out = await running(ListSource(frames=[frame(i / 20) for i in range(3)]), speed=10)
    await command(once, PlayCommand())
    await until(lambda: once.ended)
    assert once.paused and once.status().ended
    await command(once, PlayCommand())  # play after the end starts over
    await until(lambda: len(frames(out)) >= 5)
    await once.stop()


async def test_step_forward_and_back():
    player, out = await running(ListSource())
    await command(player, StepCommand(n=3))
    assert player.cursor == at(0.15)
    await command(player, StepCommand(n=-1))
    assert player.cursor == at(0.1) and frames(out)[-1] == at(0.1)
    await command(player, StepCommand(n=-10))
    assert player.cursor == at(0)
    await player.stop()


async def test_seek_shows_the_frame_there_and_a_chunk_ends_paused():
    player, out = await running(ListSource())
    await command(player, SeekCommand(offset_s=0.5))
    assert (player.cursor, frames(out)[-1], player.paused) == (at(0.5), at(0.5), True)
    await command(player, SeekCommand(offset_s=0.2, end_offset_s=0.4, play=True))
    assert player.status().range_end == at(0.4)
    await until(lambda: player.ended)
    assert frames(out)[-4:] == [at(0.2), at(0.25), at(0.3), at(0.35)] and player.paused
    await player.stop()


async def test_what_does_not_apply_is_refused():
    player, _ = await running(ListSource())
    with pytest.raises(CommandRefused):
        player.validate(SeekCommand(offset_s=5))  # the recording is one second long
    await player.stop()


async def test_a_command_to_a_stopped_playable_is_refused_and_it_can_start_again():
    player, out = await running(ListSource(), speed=4)
    await player.stop()
    with pytest.raises(CommandRefused, match="not running"):
        await player.handle(PlayCommand())
    await player.start(out)  # as a run does on switching back
    status = player.status()
    assert (status.paused, status.cursor, status.speed) == (True, at(0), 4.0)  # speed carries over
    await player.stop()


async def test_a_provider_failure_stops_the_stream_and_play_tries_again():
    player, out = await running(Failing(after=5), speed=10)
    await command(player, PlayCommand())
    (error,) = await out.wait_for(ErrorEvent)
    assert error.source == "player" and "store went away" in error.detail
    status = player.status()
    assert status.paused and status.ended and "ConnectionError" in status.error
    await command(player, PlayCommand())
    assert player.error is None and not player.paused
    await player.stop()


async def test_an_unreachable_source_starts_anyway_and_says_why():
    player, out = await running(Unreachable("store"))
    status = player.status()
    assert status.error and "no route to host" in status.error and not status.can_seek
    assert out.of(ErrorEvent) and out.of(PlayerStatus)
    await player.stop()


async def test_a_blocking_source_replays_through_a_thread():
    player, out = await running(Thready(), speed=10)
    await command(player, PlayCommand())
    await until(lambda: len(frames(out)) >= 20)
    assert frames(out)[:20] == [at(i / 20) for i in range(20)]
    await player.stop()


async def test_frames_pass_through_the_enrichers_given_at_start():
    player, out = await running(ListSource(), enrichers=[CimReferenceEnricher("ref-1")])
    assert out.of(PmuFrame)[0].header.cimReferenceId == "ref-1"
    await player.stop()


async def test_the_playable_leaves_its_source_open_for_the_set_to_close():
    source = ListSource()
    player, _ = await running(source)
    await player.stop()
    assert (source.opened, source.closed) == (1, 0)
    await source._ensure_closed()
    assert source.closed == 1
