"""The router over a run's sources: switching, routing the playback commands to
the playable source, pumping the others, and what it refuses. (The pacing of a
recording is ``test_playable.py``'s; a router over a run is ``test_pipeline.py``'s.)"""

from __future__ import annotations

import asyncio

import pytest
from support import AsyncListSource, ListSource, Recorder, TickingSource, at, frame

from pswamp_core.active_source import ROUTER_COMMANDS, ActiveSource
from pswamp_core.command_routing import CommandRefused
from pswamp_core.sources import SourceModule, SourceSet
from pswamp_core.util.time import utcnow
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


async def running(*sources, loop=False, speed=None, follow_live=False) -> tuple[ActiveSource, Recorder]:
    out = Recorder()
    router = ActiveSource(SourceSet(list(sources)), out, loop=loop, follow_live=follow_live)
    await router.start()
    if speed is not None:
        await command(router, SpeedCommand(speed=speed))
    return router, out


async def command(router: ActiveSource, cmd) -> None:
    router.validate(cmd)
    await router.handle(cmd)


async def until(condition, timeout: float = 5.0) -> None:
    async def poll():
        while not condition():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(poll(), timeout)


class Silent(SourceModule):
    """A live feed that never says anything."""

    name = "silent-source"
    kind = "live"

    async def aread(self, start=None, end=None):
        await asyncio.Event().wait()
        yield  # pragma: no cover


class DropsOut(SourceModule):
    """A live feed that fails after its first frame."""

    name = "drops-out-source"
    kind = "live"

    async def aread(self, start=None, end=None):
        yield frame(0).model_copy(update={"timestamp": utcnow()})
        raise ConnectionError("feed went away")


class Ends(SourceModule):
    """A live feed that ends after two frames."""

    name = "ends-source"
    kind = "live"

    async def aread(self, start=None, end=None):
        for _ in range(2):
            yield frame(0).model_copy(update={"timestamp": utcnow()})


def test_the_router_takes_the_playback_commands_and_the_switch():
    assert set(ROUTER_COMMANDS) == {PlayCommand, PauseCommand, StepCommand, SeekCommand, SpeedCommand, SwitchSourceCommand}
    assert ActiveSource.name == "player"  # what errors and the tray know it by


async def test_a_recording_starts_paused_showing_its_first_frame():
    router, out = await running(ListSource("rec"), TickingSource("live"))
    status = router.status()
    assert (status.mode, status.paused, status.can_seek, status.source) == ("replay", True, True, "rec")
    assert status.sources == ["rec", "live"]
    assert (status.coverage_start, status.cursor, status.loop, status.speed) == (at(0), at(0), False, 1.0)
    assert frames(out) == [at(0)] and router.last_frame.timestamp == at(0)
    assert out.of(PlayerStatus)
    await router.stop()


async def test_playback_commands_go_to_the_active_playable():
    router, out = await running(ListSource("rec"), speed=10)
    await command(router, PlayCommand())
    await until(lambda: len(frames(out)) >= 5)
    await command(router, PauseCommand())
    await command(router, SeekCommand(offset_s=0.5))
    assert (router.status().cursor, frames(out)[-1], router.status().paused) == (at(0.5), at(0.5), True)
    await router.stop()


async def test_what_does_not_apply_is_refused():
    router, _ = await running(ListSource("rec"), TickingSource("live"))
    with pytest.raises(CommandRefused, match="lies past the end"):
        router.validate(SeekCommand(offset_s=5))  # the recording is one second long
    with pytest.raises(CommandRefused) as unknown:
        router.validate(SwitchSourceCommand(source="nope"))
    assert str(unknown.value) == "no source named 'nope'; the sources are ['rec', 'live']"
    await command(router, SwitchSourceCommand(source="live"))
    for cmd in (PlayCommand(), PauseCommand(), StepCommand(), SeekCommand(offset_s=0), SpeedCommand(speed=2)):
        with pytest.raises(CommandRefused) as refused:
            router.validate(cmd)
        assert str(refused.value) == f"{cmd.name} does not apply to a live source"
    await router.stop()


async def test_switching_to_live_follows_it_and_back_lands_paused_at_the_start():
    router, out = await running(ListSource("rec"), TickingSource("live"), speed=4)
    await command(router, SwitchSourceCommand(source="live"))
    status = router.status()
    assert (status.mode, status.paused, status.can_seek, status.coverage_start, status.speed) == ("live", False, False, None, 4.0)
    assert status.sources == ["rec", "live"]
    await until(lambda: len(frames(out)) >= 4)
    assert frames(out)[-1] > at(3600)  # stamped now, not in the recording
    assert router.status().cursor == router.last_frame.timestamp
    await command(router, SwitchSourceCommand(source="rec"))
    status = router.status()
    assert (status.mode, status.paused, status.cursor, status.speed) == ("replay", True, at(0), 4.0)  # the speed carries over
    assert out.of(PlayerStatus)[-1].mode == "replay"
    await router.stop()


async def test_a_quiet_live_feed_does_not_delay_a_command():
    router, _ = await running(ListSource("rec"), Silent("live"))
    await command(router, SwitchSourceCommand(source="live"))
    await asyncio.wait_for(command(router, SwitchSourceCommand(source="rec")), 0.5)
    assert router.status().mode == "replay"
    await router.stop()


async def test_a_run_that_follows_a_live_source_opens_nothing():
    ticker = TickingSource("live")
    router, out = await running(ListSource("rec"), ticker, follow_live=True)
    await command(router, SwitchSourceCommand(source="live"))
    await asyncio.sleep(0.1)
    status = router.status()
    assert (status.mode, status.paused, status.cursor, status.source) == ("live", False, None, "live")
    assert ticker.opened == 0 and len(frames(out)) == 1  # only the recording's first frame, from before
    await router.stop()


async def test_a_live_feed_that_fails_or_ends_stops_with_an_error():
    router, out = await running(ListSource("rec"), DropsOut("flaky"), Ends("short"))
    await command(router, SwitchSourceCommand(source="flaky"))
    (error,) = await out.wait_for(ErrorEvent)
    assert error.source == "player" and "feed went away" in error.detail
    status = router.status()
    assert status.mode == "live" and status.paused and status.ended and "ConnectionError" in status.error
    await command(router, SwitchSourceCommand(source="short"))
    await until(lambda: len(out.of(ErrorEvent)) == 2)
    assert "the live feed ended" in out.of(ErrorEvent)[1].detail and router.status().ended
    await router.stop()


async def test_a_history_that_is_not_playable_is_pumped_to_its_end():
    router, out = await running(ListSource("rec"), AsyncListSource("plain"))
    await command(router, SwitchSourceCommand(source="plain"))
    await until(lambda: router.status().ended)
    status = router.status()
    assert (status.mode, status.can_seek, status.paused) == ("replay", False, True)
    assert frames(out)[-20:] == [at(i / 20) for i in range(20)]
    with pytest.raises(CommandRefused, match="play does not apply: plain is not playable"):
        router.validate(PlayCommand())
    await router.stop()


async def test_a_stopped_router_refuses_commands():
    router, _ = await running(ListSource("rec"))
    await router.stop()
    with pytest.raises(CommandRefused, match="not running"):
        await router.handle(PlayCommand())
