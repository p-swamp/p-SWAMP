"""Review findings on the recorder's store, each reproduced by a test.

Each test is ``xfail(strict=True)`` until the commit that fixes it removes the marker, so the suite
is green throughout and a fix that does not work (or a finding that is not real) is noticed.
"""

import threading
import tracemalloc
from datetime import UTC, datetime, timedelta

import pytest
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


@pytest.mark.xfail(strict=True, reason="finding 3: overlapping segments are read back to back, so time runs backwards")
def test_a_read_over_overlapping_segments_ends_where_coverage_ends(tmp_path):
    """A stream replayed over a span already recorded: its segment is inside an older one's span."""
    store = Store(tmp_path, flush_every=timedelta(hours=1))
    for i in range(10):
        store.append(frame(i))
    store.roll_over()
    for i in (3, 4):
        store.append(frame(i))
    store.flush()
    reader = Store(tmp_path)
    read = list(reader.read())
    first, last = reader.bounds()
    assert read[0].timestamp == first
    assert read[-1].timestamp == last
