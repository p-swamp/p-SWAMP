"""The player: paced replay, followed live feeds, the controls, and failures."""

from __future__ import annotations

import asyncio
import time

import pytest
from support import ListClient, Recorder, TickingClient, at, frame

from pswamp_core.command_routing import CommandRefused
from pswamp_core.datagateway import DataGateway, TimeRange
from pswamp_core.messages import (
    ErrorEvent,
    PauseCommand,
    PlayCommand,
    PlayerStatus,
    PmuFrame,
    SeekCommand,
    SpeedCommand,
    StepCommand,
    SwitchSourceCommand,
)
from pswamp_core.player import Player


def frames(out: Recorder) -> list:
    return [f.timestamp for f in out.of(PmuFrame)]


async def running(*clients, loop=False, speed=None) -> tuple[Player, Recorder]:
    out = Recorder()
    player = Player(DataGateway(list(clients)), out, loop=loop)
    await player.start()
    if speed is not None:
        await command(player, SpeedCommand(speed=speed))
    return player, out


async def command(player: Player, cmd) -> None:
    player.validate(cmd)
    await player.handle(cmd)


async def until(condition, timeout: float = 5.0) -> None:
    async def poll():
        while not condition():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(poll(), timeout)


class Failing(ListClient):
    """Fails after ``after`` frames."""

    def __init__(self, after: int) -> None:
        super().__init__("flaky")
        self.after = after

    async def consume(self, time_range):
        count = 0
        async for record in super().consume(time_range):
            if count == self.after:
                raise ConnectionError("store went away")
            count += 1
            yield record


class Unreachable(ListClient):
    async def coverage(self):
        raise ConnectionError("no route to host")


class Silent(TickingClient):
    async def consume(self, time_range: TimeRange):
        await asyncio.Event().wait()
        yield  # pragma: no cover


async def test_a_recording_starts_paused_showing_its_first_frame():
    player, out = await running(ListClient())
    status = player.status()
    assert (status.mode, status.paused, status.can_seek, status.source) == ("replay", True, True, "list")
    assert (status.coverage_start, status.cursor) == (at(0), at(0))
    assert frames(out) == [at(0)]
    await player.stop()


async def test_play_paces_frames_in_order_and_pause_stops_without_skipping():
    player, out = await running(ListClient(), speed=10)  # 20 frames at 20 Hz: 0.1 s
    began = time.monotonic()
    await command(player, PlayCommand())
    await until(lambda: len(frames(out)) >= 6)
    assert time.monotonic() - began >= 0.02  # paced, not a burst
    await command(player, PauseCommand())
    paused_at = len(frames(out))
    await asyncio.sleep(0.05)
    assert len(frames(out)) == paused_at
    await command(player, PlayCommand())
    await until(lambda: len(frames(out)) >= 20)
    assert frames(out)[:20] == [at(i / 20) for i in range(20)]
    await player.stop()


async def test_the_end_loops_or_ends_paused():
    looping, out = await running(ListClient(frames=[frame(i / 20) for i in range(3)]), loop=True, speed=10)
    await command(looping, PlayCommand())
    await until(lambda: len(frames(out)) >= 7)
    assert frames(out)[:7] == [at(0), at(0.05), at(0.1), at(0), at(0.05), at(0.1), at(0)]
    await looping.stop()
    once, out = await running(ListClient(frames=[frame(i / 20) for i in range(3)]), speed=10)
    await command(once, PlayCommand())
    await until(lambda: once.ended)
    assert once.paused and once.status().ended
    await command(once, PlayCommand())  # play after the end starts over
    await until(lambda: len(frames(out)) >= 5)
    await once.stop()


async def test_step_forward_and_back():
    player, out = await running(ListClient())
    await command(player, StepCommand(n=3))
    assert player.cursor == at(0.15)
    await command(player, StepCommand(n=-1))
    assert player.cursor == at(0.1) and frames(out)[-1] == at(0.1)
    await command(player, StepCommand(n=-10))
    assert player.cursor == at(0)
    await player.stop()


async def test_seek_shows_the_frame_there_and_a_chunk_ends_paused():
    player, out = await running(ListClient())
    await command(player, SeekCommand(offset_s=0.5))
    assert (player.cursor, frames(out)[-1], player.paused) == (at(0.5), at(0.5), True)
    await command(player, SeekCommand(offset_s=0.2, end_offset_s=0.4, play=True))
    assert player.status().range_end == at(0.4)
    await until(lambda: player.ended)
    assert frames(out)[-4:] == [at(0.2), at(0.25), at(0.3), at(0.35)] and player.paused
    await player.stop()


async def test_what_does_not_apply_is_refused():
    player, _ = await running(ListClient("rec"), TickingClient("live"))
    with pytest.raises(CommandRefused):
        player.validate(SeekCommand(offset_s=5))  # the recording is one second long
    with pytest.raises(CommandRefused):
        player.validate(SwitchSourceCommand(source="nope"))
    await command(player, SwitchSourceCommand(source="live"))
    for cmd in (PlayCommand(), PauseCommand(), StepCommand(), SeekCommand(offset_s=0), SpeedCommand(speed=2)):
        with pytest.raises(CommandRefused, match="live"):
            player.validate(cmd)
    await player.stop()


async def test_switching_to_live_follows_it_and_back_lands_paused_at_the_start():
    player, out = await running(ListClient("rec"), TickingClient("live"))
    await command(player, SwitchSourceCommand(source="live"))
    status = player.status()
    assert (status.mode, status.paused, status.can_seek, status.coverage_start) == ("live", False, False, None)
    await until(lambda: len(frames(out)) >= 4)
    assert frames(out)[-1] > at(3600)  # stamped now, not in the recording
    await command(player, SwitchSourceCommand(source="rec"))
    assert (player.status().mode, player.paused, player.cursor) == ("replay", True, at(0))
    await player.stop()


async def test_a_quiet_live_feed_does_not_delay_a_command():
    player, _ = await running(ListClient("rec"), Silent("live"))
    await command(player, SwitchSourceCommand(source="live"))
    await asyncio.wait_for(command(player, SwitchSourceCommand(source="rec")), 0.5)
    assert player.status().mode == "replay"
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
