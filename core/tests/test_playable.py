"""``Playable``: paced replay, the controls, and failures, against a playable source.
(What the run decides rather than the source, switching to a live feed and the
live refusals, is ``test_active_source.py``'s.)"""

from __future__ import annotations

import asyncio
import time
from datetime import timedelta

import pytest
from support import HEADER, ListSource, Recorder, at, frame

from pswamp_core.command_routing import CommandRefused
from pswamp_core.enrich import CimReferenceEnricher
from pswamp_core.playable import PLAYBACK_COMMANDS, Playable
from pswamp_core.settings import EnvSetting
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
    await player.ahandle(cmd)


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

            async def aread(self, start=None, end=None):
                for record in ():
                    yield record


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
    await command(player, SeekCommand(at=at(0.5)))
    assert (player.cursor, frames(out)[-1], player.paused) == (at(0.5), at(0.5), True)
    await command(player, SeekCommand(at=at(0.2), until=at(0.4), play=True))
    assert player.status().range_end == at(0.4)
    await until(lambda: player.ended)
    assert frames(out)[-4:] == [at(0.2), at(0.25), at(0.3), at(0.35)] and player.paused
    await player.stop()


async def test_streams_count_the_start_a_seek_a_step_back_and_a_loop():
    player, out = await running(ListSource(frames=[frame(i / 20) for i in range(3)]), loop=True, speed=10)
    assert player.streams == 1
    await command(player, StepCommand(n=2))
    assert player.streams == 1  # forward is the same stream
    await command(player, StepCommand(n=-1))
    await command(player, SeekCommand(at=at(0.05)))
    assert player.streams == 3
    await command(player, PlayCommand())
    await until(lambda: player.streams >= 5)  # it loops
    await player.stop()


async def test_what_does_not_apply_is_refused():
    player, _ = await running(ListSource())
    with pytest.raises(CommandRefused):
        player.validate(SeekCommand(at=at(5)))  # the recording is one second long
    await player.stop()


def test_a_playable_is_a_module_whose_commands_need_its_running_player():
    source = ListSource()
    assert source._overrides("ahandle") and not source._overrides("handle")
    with pytest.raises(CommandRefused, match="not running"):
        source.run_command(PlayCommand())  # a fresh loop: no player there


async def test_arun_command_drives_a_started_playable_and_answers_through_its_sink():
    player, out = await running(ListSource())
    assert await player.arun_command(SeekCommand(at=at(0.5))) == []
    await until(lambda: player.status().cursor == at(0.5))
    await player.stop()


async def test_a_command_to_a_stopped_playable_is_refused_and_it_can_start_again():
    player, out = await running(ListSource(), speed=4)
    await player.stop()
    with pytest.raises(CommandRefused, match="not running"):
        await player.ahandle(PlayCommand())
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


def made_under(grid: str | None) -> ListSource:
    """A recording whose frames already carry the id of the grid they were made under."""
    header = HEADER.model_copy(update={"cimReferenceId": grid})
    return ListSource(frames=[frame(i / 20, header=header) for i in range(20)])


async def test_a_recording_made_under_another_grid_says_so_once_and_plays_on():
    player, out = await running(made_under("grid-old"), enrichers=[CimReferenceEnricher("grid-new")])
    await command(player, PlayCommand())
    await until(lambda: len(out.of(PmuFrame)) >= 5)
    (report,) = [e for e in out.of(ErrorEvent) if "grid" in e.message]
    assert "grid-old" in report.detail and "grid-new" in report.detail
    assert out.of(PmuFrame)[0].header.cimReferenceId == "grid-old"  # the frames keep the id they were made under
    await player.stop()


@pytest.mark.parametrize("grid", ["grid-new", None])
async def test_a_recording_under_this_grid_or_none_says_nothing(grid):
    player, out = await running(made_under(grid), enrichers=[CimReferenceEnricher("grid-new")])
    await command(player, PlayCommand())
    await until(lambda: len(out.of(PmuFrame)) >= 5)
    assert [e for e in out.of(ErrorEvent) if "grid" in e.message] == []
    await player.stop()


async def test_a_run_tied_to_no_grid_says_nothing_about_a_recording_made_under_one():
    player, out = await running(made_under("grid-old"))
    await command(player, PlayCommand())
    await until(lambda: len(out.of(PmuFrame)) >= 5)
    assert out.of(ErrorEvent) == []
    await player.stop()


async def test_the_playable_leaves_its_source_open_for_the_set_to_close():
    source = ListSource()
    player, _ = await running(source)
    await player.stop()
    assert (source.opened, source.closed) == (1, 0)
    await source._ensure_closed()
    assert source.closed == 1


# --- gaps ----------------------------------------------------------------------------


def with_gap() -> ListSource:
    """0 to 0.2 s, nothing for 29.8 s, then 30 to 30.2 s, at 20 Hz."""
    return ListSource(frames=[frame(i / 20) for i in range(5)] + [frame(30 + i / 20) for i in range(5)])


async def test_a_gap_is_crossed_at_once_and_reported_once():
    player, out = await running(with_gap())  # real time: waiting out the gap would take 30 s
    began = time.perf_counter()
    await command(player, PlayCommand())
    await until(lambda: player.ended, timeout=3)
    assert time.perf_counter() - began < 2
    assert frames(out) == [at(i / 20) for i in range(5)] + [at(30 + i / 20) for i in range(5)]
    (gap,) = out.of(ErrorEvent)
    assert (gap.source, gap.message) == ("player", "no data from list for 29.80 s")
    assert gap.detail.startswith("2026-01-01 00:00:00.200 to 2026-01-01 00:00:30.000 UTC")
    await player.stop()


async def test_a_seek_into_a_gap_lands_after_it_and_says_so():
    player, out = await running(with_gap())
    await command(player, SeekCommand(at=at(10)))
    assert (player.cursor, frames(out)[-1]) == (at(30), at(30))
    (gap,) = out.of(ErrorEvent)
    assert gap.message == "no data from list for 20.00 s"
    assert gap.detail.startswith("2026-01-01 00:00:10.000 to 2026-01-01 00:00:30.000 UTC")
    await player.stop()


async def test_a_chunk_with_no_data_says_so():
    player, out = await running(with_gap())
    await command(player, SeekCommand(at=at(5), until=at(10)))
    assert player.ended and player.paused
    (gap,) = out.of(ErrorEvent)
    assert gap.message == "no data from list in the range asked for"
    assert gap.detail == "2026-01-01 00:00:05.000 to 2026-01-01 00:00:10.000 UTC"
    await player.stop()


async def test_steps_seeks_and_loops_without_a_gap_report_none():
    player, out = await running(ListSource(frames=[frame(i / 20) for i in range(4)]), loop=True, speed=10)
    await command(player, StepCommand(n=2))
    await command(player, StepCommand(n=-1))
    await command(player, SeekCommand(at=at(0.1)))
    await command(player, PlayCommand())
    await until(lambda: player.streams >= 6)  # it has looped to the start, twice
    assert out.of(ErrorEvent) == []
    await player.stop()


async def test_a_slow_stream_s_frames_are_not_gaps():
    slow = HEADER.model_copy(update={"data_rate": 1 / 1.5})  # a frame every 1.5 s, beyond the 1 s GAP
    player, out = await running(ListSource(frames=[frame(i * 1.5, header=slow) for i in range(3)]), speed=10)
    await command(player, PlayCommand())
    await until(lambda: player.ended)
    assert len(frames(out)) == 3 and out.of(ErrorEvent) == []
    await player.stop()


async def test_reports_are_limited_and_the_limit_restarts_with_each_stream():
    every_2_s = ListSource(frames=[frame(i * 2.0) for i in range(10)])  # nine gaps
    player, out = await running(every_2_s)
    await command(player, PlayCommand())
    await until(lambda: player.ended, timeout=3)
    assert len(out.of(ErrorEvent)) == 1  # the other eight are held for the next report
    player._pl_gap_reported -= 10  # as if ten seconds had passed
    player._pl_report_gap(at(100), at(102))
    assert out.of(ErrorEvent)[-1].detail.endswith("(and 8 more gaps since the last report)")
    await command(player, SeekCommand(at=at(0.5)))  # a new stream: lands in a gap, reported at once
    assert len(out.of(ErrorEvent)) == 3 and out.of(ErrorEvent)[-1].message == "no data from list for 1.50 s"
    await player.stop()


async def test_the_gap_is_a_setting():
    class OwnGap(ListSource):
        name = "own-gap-list-source"
        env_settings = (EnvSetting("GAP", "longer here", default="60", kind="seconds"),)

    assert [s.setting for s in ListSource.env_settings].count("GAP") == 1
    assert [s.setting for s in Failing.env_settings].count("GAP") == 1  # a subclass, not twice
    assert OwnGap(frames=[frame(0)]).settings.gap == timedelta(seconds=60)
    player, out = await running(ListSource(frames=with_gap().frames, gap=60), speed=100)
    began = time.perf_counter()
    await command(player, PlayCommand())
    await until(lambda: player.ended, timeout=3)
    assert time.perf_counter() - began >= 0.25  # 29.8 s at 100×: waited out, not crossed
    assert out.of(ErrorEvent) == []
    await player.stop()


def test_the_gap_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("LIST_GAP", "5")
    assert ListSource.from_env("list").settings.gap == timedelta(seconds=5)
