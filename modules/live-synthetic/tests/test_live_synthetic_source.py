"""The synthetic live source: the conformance cases and what it ticks."""

from __future__ import annotations

from datetime import timedelta

import pytest

from pswamp_core.playable import Playable
from pswamp_core.testing import SourceConformance
from pswamp_core.util.time import utcnow
from pswamp_models.pmu import PmuFrame
from pswamp_modules.live_synthetic import LiveSynthetic
from pswamp_modules.live_synthetic.sample import DEFAULT_PATH, load_sample
from pswamp_modules.live_synthetic.source import LIVE_STREAM_ID


class TestLiveSyntheticConformance(SourceConformance):
    @pytest.fixture
    def source_under_test(self):
        return LiveSynthetic()


def test_it_is_a_live_source_and_not_playable():
    assert (LiveSynthetic.name, LiveSynthetic.kind, LiveSynthetic.outputs) == ("live-synthetic", "live", (PmuFrame,))
    assert not issubclass(LiveSynthetic, Playable) and LiveSynthetic.commands == ()
    assert LiveSynthetic().source == "live-synthetic" and LiveSynthetic("live").source == "live"


def test_a_script_reads_a_bounded_stretch_of_it_with_no_event_loop():
    start = utcnow()
    frames = list(LiveSynthetic().read(end=start + timedelta(seconds=0.5)))
    assert 5 <= len(frames) <= 12  # 20 Hz for half a second
    first, second = frames[0], frames[1]
    assert first.mRID == LIVE_STREAM_ID and first.header == load_sample().header
    assert 0.02 < (second.timestamp - first.timestamp).total_seconds() < 0.2
    assert all(start <= f.timestamp for f in frames)


async def test_the_host_reads_it_without_a_thread_and_each_reader_gets_the_feed():
    source = LiveSynthetic()
    one, two = source.aread(), source.aread()
    a, b = await anext(one), await anext(two)
    assert a.header == b.header and a.mRID == b.mRID == LIVE_STREAM_ID
    await one.aclose()
    await two.aclose()


def test_another_file_is_a_setting(tmp_path, monkeypatch):
    lines = DEFAULT_PATH.read_text().splitlines()[:10]
    mine = tmp_path / "mine.txt"
    mine.write_text("\n".join(lines))
    assert len(LiveSynthetic(path=mine).recording.frames) == 2
    monkeypatch.setenv("LIVE_PATH", str(mine))
    assert len(LiveSynthetic.from_env("live").recording.frames) == 2
