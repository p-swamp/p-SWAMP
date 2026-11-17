"""Review findings on the recorder's store, each pinned by a test: a flush that does not lose a
concurrent append, a read that streams, and the order overlapping segments are read in."""

import threading
import tracemalloc
from datetime import UTC, datetime, timedelta

from pswamp_models.pmu import PmuFrame, PmuHeader
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


def test_a_frame_appended_while_a_flush_is_writing_is_not_lost(tmp_path):
    """The run flushes a quiet recorder from a worker thread while ``process`` may append from another."""
    store = Store(tmp_path, flush_every=timedelta(hours=1))
    store.append(frame(0))
    late = frame(1)
    real = store._write
    other = threading.Thread(target=store.append, args=(late,))

    def write_while_another_thread_appends() -> None:
        real()
        other.start()
        other.join(timeout=0.5)  # a store that serialises writes holds this thread off until the flush ends

    store._write = write_while_another_thread_appends  # type: ignore[method-assign]
    store.flush()
    store._write = real  # type: ignore[method-assign]
    other.join()
    store.flush()
    assert list(Store(tmp_path).read()) == [frame(0), late]


def test_reading_the_first_frame_does_not_load_the_whole_segment(tmp_path):
    store = Store(tmp_path, flush_every=timedelta(hours=1), roll=timedelta(days=1))
    for i in range(20_000):
        store.append(frame(i))
    store.flush()
    reader = Store(tmp_path)
    tracemalloc.start()
    try:
        first = next(iter(reader.read()))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert first == frame(0)
    assert peak < 5 * 1024**2


def test_overlapping_segments_are_each_read_whole_and_back_to_back(tmp_path):
    """A stream replayed over a span already recorded: its segment is inside an older one's span.

    A segment is one run, so a read plays each in order and does not interleave two runs; time may
    therefore step back at a segment boundary, while ``bounds`` spans every segment.
    """
    store = Store(tmp_path, flush_every=timedelta(hours=1))
    for i in range(10):
        store.append(frame(i))
    store.roll_over()
    for i in (3, 4):
        store.append(frame(i))
    store.flush()
    reader = Store(tmp_path)
    assert list(reader.read()) == [frame(i) for i in (*range(10), 3, 4)]
    assert reader.bounds() == (frame(0).timestamp, frame(9).timestamp)
    # A range still filters each segment on its own.
    assert list(reader.read(frame(4).timestamp, frame(6).timestamp)) == [frame(4), frame(5), frame(4)]
