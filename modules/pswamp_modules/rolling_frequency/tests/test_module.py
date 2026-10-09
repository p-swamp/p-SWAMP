"""The Rolling frequency module, bottom up: the analysis, the window, then what
``run`` publishes around it (the warm-up, and starting over at a break)."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from pswamp_core.messages import PmuFrame, PmuHeader
from pswamp_core.subscription import Overflow, Subscription
from pswamp_modules.pipelines.rolling_frequency import PIPELINE
from pswamp_modules.rolling_frequency import WINDOW_S, RollingFrequencyModule, mean_of

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
HEADER = PmuHeader(station=["a", "b"], channel=["f", "f"], measurement=["f", "f"], units=["Hz", "Hz"], data_rate=10.0)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def frame(tenths: int, hz: float, stream: str | None = None, seq: int | None = None) -> PmuFrame:
    """The frame ``tenths`` of a second in, both stations at ``hz``, as number ``seq`` of ``stream``."""
    return PmuFrame(mRID="test", timestamp=at(tenths / 10), header=HEADER, values=[hz, hz], stream=stream, seq=seq)


def test_the_mean_skips_what_is_missing():
    assert mean_of([49.0, None, 51.0]) == 50.0
    assert mean_of([None]) is None and mean_of([]) is None


async def test_the_result_is_the_mean_over_the_last_five_seconds():
    module = RollingFrequencyModule()
    bodies = [await module.process(frame(i, 50.0 if i < 60 else 51.0)) for i in range(101)]
    assert (bodies[0].samples, bodies[50].samples, bodies[100].samples) == (1, 51, 51)  # 5 s at 10 Hz, both ends
    assert bodies[50].mean_hz == 50.0 and bodies[50].window_s == WINDOW_S
    assert bodies[100].mean_hz == pytest.approx((10 * 50.0 + 41 * 51.0) / 51)  # 5.0 to 5.9 s at 50, the rest at 51
    assert await module.process(frame(101, None)) is None  # no station has a value


async def test_reset_empties_the_window():
    module = RollingFrequencyModule()
    for i in range(20):
        await module.process(frame(i, 50.0))
    module.reset()
    body = await module.process(frame(5, 49.0))
    assert (body.samples, body.mean_hz) == (1, 49.0)


# --- as a host runs it ----------------------------------------------------------------


class Recorder:
    def __init__(self) -> None:
        self.published: list = []

    def publish(self, message) -> None:
        self.published.append(message)


class _NoOwner:
    def _detach(self, subscription) -> None:
        return


async def published_for(frames: list[PmuFrame]) -> list:
    """What a fresh module's ``run`` publishes for ``frames``."""
    inputs, out = Subscription(_NoOwner(), (PmuFrame,), Overflow.GROW, 0), Recorder()
    for one in frames:
        inputs.offer(one)
    inputs.close()  # run ends once it has read them all
    await asyncio.wait_for(RollingFrequencyModule().run(inputs, out), 5)
    return out.published


async def test_nothing_is_published_until_five_seconds_of_frames_are_in():
    results = await published_for([frame(i, 50.0, "a", i) for i in range(61)])  # 0 to 6.0 s
    assert [r.timestamp for r in results] == [at(5 + i / 10) for i in range(11)]
    assert all(r.result.samples == 51 and r.stream == "a" for r in results)


async def test_a_seek_starts_the_window_over():
    played = [frame(i, 50.0, "a", i) for i in range(61)]  # 0 to 6.0 s, at 50 Hz
    sought = [frame(20 + i, 51.0, "b", i) for i in range(51)]  # then from 2.0 s again, as if at 51 Hz
    results = await published_for(played + sought)
    after = [r for r in results if r.stream == "b"]
    assert [r.timestamp for r in after] == [at(7.0)]  # 5 s after the seek, not before
    assert (after[0].result.mean_hz, after[0].result.samples) == (51.0, 51)  # nothing of the first pass is in it


async def test_a_missing_frame_starts_the_window_over():
    frames = [frame(i, 50.0, "a", i) for i in range(91) if i != 30]  # 0 to 9.0 s, without frame 30
    results = await published_for(frames)
    assert [r.timestamp for r in results] == [at(8.1 + i / 10) for i in range(10)]  # 5 s after frame 31
    assert results[0].result.samples == 51


def test_its_pipeline_lets_its_results_be_kept():
    assert PIPELINE.modules == (RollingFrequencyModule,)
    assert RollingFrequencyModule.cache_results and RollingFrequencyModule.warm_up_s == WINDOW_S
