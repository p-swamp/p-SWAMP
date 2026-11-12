"""The Recorder: what it is fed, it holds, and reads back."""

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest
from pswamp_core.testing import SourceConformance
from pswamp_models.pmu import PmuFrame, PmuHeader
from pswamp_modules.recorder import Recorder
from pswamp_modules.recorder import store as store_module
from pswamp_modules.recorder.store import Store

T0 = datetime(2026, 3, 14, 13, 5, tzinfo=UTC)
HEADER = PmuHeader(
    station=["3000", "3000"],
    channel=["V", "f"],
    measurement=["V_Magnitude", "f"],
    units=["kV", "Hz"],
    data_rate=50.0,
)


def frame(i: int) -> PmuFrame:
    return PmuFrame(
        timestamp=T0 + timedelta(milliseconds=20 * i), mRID="test", header=HEADER, values=[420.0 + i, 50.0 + i / 1000]
    )


class TestRecorderAsASource(SourceConformance):
    """Range, coverage, seek and the sync/async reads: what every history source passes."""

    @pytest.fixture
    def conformance_records(self):
        return [frame(i) for i in range(60)]

    @pytest.fixture
    def source_under_test(self, tmp_path, conformance_records):
        recorder = Recorder(dir=tmp_path)
        for each in conformance_records:
            recorder.run(each)
        recorder.flush()
        return Recorder(dir=tmp_path)


def feed(recorder, frames):
    for each in frames:
        recorder.run(each)
    recorder.flush()


def test_a_new_layout_starts_a_new_segment(tmp_path):
    other = PmuHeader(station=["3000"], channel=["f"], measurement=["f"], units=["Hz"], data_rate=50.0)
    frames = [frame(0), frame(1), PmuFrame(timestamp=frame(2).timestamp, mRID="test", header=other, values=[50.0]), frame(3)]
    recorder = Recorder(dir=tmp_path)
    feed(recorder, frames)
    assert len(recorder.store.segments()) == 3  # layout A, layout B, layout A again
    assert list(Recorder(dir=tmp_path).read()) == frames


def test_a_change_of_grid_starts_a_new_segment_and_each_frame_keeps_its_grid(tmp_path):
    def under(grid):
        return HEADER.model_copy(update={"cimReferenceId": grid})

    frames = [
        PmuFrame(timestamp=frame(i).timestamp, mRID="test", header=under("grid-1" if i < 2 else "grid-2"), values=[1.0, 2.0])
        for i in range(4)
    ]
    recorder = Recorder(dir=tmp_path)
    feed(recorder, frames)
    assert len(recorder.store.segments()) == 2
    assert list(Recorder(dir=tmp_path).read()) == frames


def test_a_restarted_stream_starts_a_new_segment(tmp_path):
    recorder = Recorder(dir=tmp_path)
    feed(recorder, [frame(0), frame(1)])
    recorder.reset()
    feed(recorder, [frame(2), frame(3)])
    assert len(recorder.store.segments()) == 2


def test_a_segment_rolls_after_roll_hours_and_a_read_crosses_the_boundary(tmp_path):
    frames = [frame(i) for i in range(10)]
    recorder = Recorder(dir=tmp_path, roll_hours=0.00001)  # 36 ms: every second frame
    feed(recorder, frames)
    assert len(recorder.store.segments()) == 5
    reader = Recorder(dir=tmp_path)
    assert list(reader.read()) == frames
    assert list(reader.read(frames[1].timestamp, frames[8].timestamp)) == frames[1:8]
    assert reader.coverage().contains(frames[0].timestamp) and reader.coverage().contains(frames[-1].timestamp)


def test_over_max_bytes_the_oldest_segments_go_and_the_open_one_stays(tmp_path):
    frames = [frame(i) for i in range(10)]
    recorder = Recorder(dir=tmp_path, roll_hours=0.00001, max_bytes=1)
    feed(recorder, frames)
    assert len(recorder.store.segments()) == 1
    assert list(Recorder(dir=tmp_path).read()) == frames[8:]  # the open segment alone


def test_under_max_bytes_nothing_is_deleted(tmp_path):
    frames = [frame(i) for i in range(10)]
    recorder = Recorder(dir=tmp_path, roll_hours=0.00001)
    feed(recorder, frames)
    assert list(Recorder(dir=tmp_path).read()) == frames


def test_frames_reach_the_disk_without_an_explicit_flush_when_flush_seconds_is_zero(tmp_path):
    recorder = Recorder(dir=tmp_path, flush_seconds=0)
    recorder.run(frame(0))
    assert list(Recorder(dir=tmp_path).read()) == [frame(0)]


def test_teardown_flushes(tmp_path):
    recorder = Recorder(dir=tmp_path, flush_seconds=3600)
    recorder.run(frame(0))
    assert recorder.store.segments() == []  # still buffered
    asyncio.run(recorder.teardown())
    assert list(Recorder(dir=tmp_path).read()) == [frame(0)]


def test_the_live_source_it_records_is_a_setting(tmp_path, monkeypatch):
    monkeypatch.setenv("RECORDED_DIR", str(tmp_path))
    monkeypatch.setenv("RECORDED_FEED", "rtsim")
    assert Recorder.from_env("recorded").settings.feed == "rtsim"
    assert Recorder(dir=tmp_path).settings.feed is None  # records nothing unless told what


def test_a_recorder_that_holds_nothing_has_no_coverage(tmp_path):
    assert Recorder(dir=tmp_path).coverage() is None
    assert list(Recorder(dir=tmp_path).read()) == []


def test_what_is_recorded_is_read_back_in_order(tmp_path):
    frames = [frame(i) for i in range(5)]
    recorder = Recorder(dir=tmp_path)
    for each in frames:
        assert recorder.run(each) == []  # it records; it publishes nothing
    recorder.flush()
    assert list(Recorder(dir=tmp_path).read()) == frames


def test_a_stream_that_starts_again_at_the_same_instant_is_a_segment_of_its_own(tmp_path):
    first = [frame(0), frame(1)]
    feed(Recorder(dir=tmp_path), first)
    second = [PmuFrame(timestamp=f.timestamp, mRID="test", header=HEADER, values=[1.0, 2.0]) for f in first]
    feed(Recorder(dir=tmp_path), second)  # a restarted process, a stream with the same first timestamp
    reader = Recorder(dir=tmp_path)
    assert len(reader.store.segments()) == 2
    assert list(reader.read()) == first + second  # nothing appended to the old segment, nothing lost


def test_a_write_the_disk_refuses_is_retried_and_no_frame_is_written_twice(tmp_path, monkeypatch):
    frames = [frame(i) for i in range(5)]
    real = store_module.duckdb.connect
    refuse = {"on": True}

    def connect(*args, **kwargs):
        if refuse["on"]:
            raise OSError("disk full")
        return real(*args, **kwargs)

    monkeypatch.setattr(store_module.duckdb, "connect", connect)
    recorder = Recorder(dir=tmp_path, flush_seconds=3600)
    for each in frames:
        recorder.run(each)
    recorder.flush()  # refused: logged, not raised
    assert len(recorder.store._buffer) == 5
    refuse["on"] = False
    recorder.flush()
    assert list(Recorder(dir=tmp_path).read()) == frames


def test_a_failed_write_is_all_or_nothing(tmp_path, monkeypatch):
    frames = [frame(i) for i in range(5)]
    recorder = Recorder(dir=tmp_path, flush_seconds=3600)
    for each in frames:
        recorder.run(each)
    real = store_module._naive
    calls = {"n": 0}

    def flaky(moment):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("mid-write")
        return real(moment)

    monkeypatch.setattr(store_module, "_naive", flaky)
    recorder.flush()  # fails part-way through building the rows; the buffer is kept
    monkeypatch.setattr(store_module, "_naive", real)
    recorder.flush()
    assert list(Recorder(dir=tmp_path).read()) == frames


def test_what_a_failing_disk_cannot_take_is_bounded_in_memory(tmp_path):
    store = Store(tmp_path, flush_every=timedelta(hours=1), max_buffer=3)
    frames = [frame(i) for i in range(10)]
    for each in frames:
        store.append(each)
    assert len(store._buffer) == 3
    store.flush()
    assert list(Store(tmp_path).read()) == frames[-3:]  # the newest are kept


def test_over_max_bytes_the_segment_written_longest_ago_goes_first(tmp_path):
    def run(i, count=3):
        return [frame(i + k) for k in range(count)]

    later_in_time = [PmuFrame(timestamp=f.timestamp + timedelta(hours=1), mRID="test", header=HEADER, values=[1.0, 2.0]) for f in run(0)]
    recorder = Recorder(dir=tmp_path)
    feed(recorder, later_in_time)  # written first, named last
    recorder.reset()
    feed(recorder, run(10))  # written second, named first
    recorder.reset()
    feed(recorder, run(20))  # the open one
    named = sorted(recorder.store.segments())
    oldest_written = named[-1]  # the one named last was written first
    os.utime(oldest_written, (1, 1))
    os.utime(named[0], (2_000_000_000, 2_000_000_000))
    recorder.store.max_bytes = sum(p.stat().st_size for p in named) - 1  # room to delete one
    recorder.store._sweep()
    assert not oldest_written.exists()
    assert len(recorder.store.segments()) == 2


def test_a_naive_timestamp_is_taken_as_utc():
    assert store_module._naive(datetime(2026, 1, 1, 12)) == datetime(2026, 1, 1, 12)
    assert store_module._naive(datetime(2026, 1, 1, 12, tzinfo=UTC)) == datetime(2026, 1, 1, 12)


def test_a_segment_the_writer_has_made_but_not_filled_is_read_as_empty(tmp_path):
    """A reader meeting the file in the instant after it is created, before its tables are."""
    store_module.duckdb.connect(str(tmp_path / "20260314T130500.000000.duckdb")).close()
    reader = Recorder(dir=tmp_path)
    assert list(reader.read()) == []
    assert reader.coverage() is None
