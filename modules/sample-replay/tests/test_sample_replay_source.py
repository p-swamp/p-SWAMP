"""The sample replay source: the file, the conformance cases, and playing it."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from pswamp_core.playable import Playable
from pswamp_core.testing import SourceConformance
from pswamp_models.player import PlayCommand, SeekCommand, SpeedCommand
from pswamp_models.pmu import PmuFrame
from pswamp_modules.sample_replay import SampleReplay
from pswamp_modules.sample_replay.sample import DEFAULT_PATH, EPOCH, STREAM_ID, load_sample


def test_the_sample_is_sixty_frames_of_five_stations_at_20_hz():
    recording = load_sample()
    assert len(recording.frames) == 60
    assert recording.header.stations == ["3000", "3245", "5100", "6500", "7000"]
    assert recording.header.data_rate == 20.0 and recording.header.n_columns == 15
    first = recording.frames[0]
    assert first.timestamp == EPOCH + timedelta(seconds=0.05) and first.mRID == STREAM_ID
    assert recording.coverage.end == EPOCH + timedelta(seconds=3.05)


def test_it_is_a_playable_history_source_named_for_its_entry_point():
    assert (SampleReplay.name, SampleReplay.kind, SampleReplay.outputs) == ("sample-replay", "history", (PmuFrame,))
    assert issubclass(SampleReplay, Playable) and PlayCommand in SampleReplay.commands
    assert SampleReplay().source == "sample-replay" and SampleReplay("sample").source == "sample"


def test_a_script_reads_it_with_no_event_loop():
    frames = list(SampleReplay().read())
    assert len(frames) == 60 and all(isinstance(f, PmuFrame) for f in frames)
    window = list(SampleReplay().read(frames[10].timestamp, frames[13].timestamp))
    assert [f.timestamp for f in window] == [f.timestamp for f in frames[10:13]]


def test_another_file_is_a_setting(tmp_path, monkeypatch):
    lines = DEFAULT_PATH.read_text().splitlines()[:10]
    mine = tmp_path / "mine.txt"
    mine.write_text("\n".join(lines))
    assert len(list(SampleReplay(path=mine).read())) == 2  # two instants of five stations
    monkeypatch.setenv("SAMPLE_PATH", str(mine))
    assert len(list(SampleReplay.from_env("sample").read())) == 2
    with pytest.raises(TypeError, match="no setting"):
        SampleReplay(url="x")


class TestSampleReplayConformance(SourceConformance):
    @pytest.fixture
    def source_under_test(self):
        return SampleReplay()

    @pytest.fixture
    def conformance_records(self):
        return list(load_sample().frames)


class Sink:
    def __init__(self) -> None:
        self.published: list = []

    def publish(self, message) -> None:
        self.published.append(message)


async def test_it_replays_paced_from_the_start_and_seeks():
    source, sink = SampleReplay(), Sink()
    await source.start(sink)
    assert source.status().can_seek and source.status().paused
    assert [m.timestamp for m in sink.published if isinstance(m, PmuFrame)] == [load_sample().frames[0].timestamp]
    await source.handle(SpeedCommand(speed=20))
    await source.handle(SeekCommand(offset_s=2.5, play=True))
    for _ in range(200):
        if source.ended:
            break
        await asyncio.sleep(0.01)
    played = [m.timestamp for m in sink.published if isinstance(m, PmuFrame)]
    assert source.ended and played[-1] == load_sample().frames[-1].timestamp
    await source.stop()
