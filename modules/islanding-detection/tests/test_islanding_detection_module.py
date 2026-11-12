"""The Islanding detection module, bottom up: the analysis, then the module around it."""

from datetime import datetime, timedelta, timezone

import numpy as np

from pswamp_models.common import AlarmEvent
from pswamp_models.islanding_detection import IslandingDetectionResult
from pswamp_models.pmu import PmuFrame, PmuHeader
from pswamp_modules.islanding_detection import IslandingDetectionModule
from pswamp_modules.islanding_detection.core import detect_islands
from pswamp_modules.islanding_detection.synthetic_cases import islanding_test_case_1

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_the_core_finds_the_islanded_channels():
    t, freq = islanding_test_case_1()
    window = (t > 30) & (t <= 40)  # well inside the first island
    _, islands = detect_islands(t[window], freq[window])
    assert [sorted(island.tolist()) for island in islands] == [[2, 3, 5]]
    _, islands = detect_islands(t[t <= 10], freq[t <= 10])
    assert islands == []


def test_the_core_waits_for_a_full_window():
    assert detect_islands(np.array([np.nan, 0.0]), np.zeros((2, 3))) is None


def steady(offsets: list[float]) -> tuple[np.ndarray, np.ndarray]:
    """10 s at 50 Hz, each station at a constant offset from 50 Hz."""
    t = np.arange(500) / 50
    return t, 50 + np.array(offsets)[None, :] + 0 * t[:, None]


def test_the_core_puts_a_station_in_one_group_only():
    # Station 2 is within the threshold of both 0 and 3, which are not of each
    # other: it joins the first group, and is not in the island too.
    _, islands = detect_islands(*steady([0, 0, 0.04, 0.08]))
    assert [island.tolist() for island in islands] == [[3]]


def test_the_core_groups_every_station():
    _, islands = detect_islands(*steady([0.1 * i for i in range(14)]))
    assert len(islands) == 13
    assert sorted(np.concatenate(islands).tolist()) == list(range(1, 14))


def test_the_core_leaves_a_station_with_a_gap_out():
    t, freq = steady([0, 0, 0, 0.2])
    freq[100, 0] = np.nan
    _, islands = detect_islands(t, freq)
    assert [island.tolist() for island in islands] == [[3]]  # the main group is 1 and 2; 0 is in none


def frames(freq: np.ndarray) -> list[PmuFrame]:
    n = freq.shape[1]
    header = PmuHeader(station=[f"s{i}" for i in range(n)], channel=["f"] * n, measurement=["f"] * n,
                       units=["Hz"] * n, data_rate=50.0)
    return [PmuFrame(mRID="test", timestamp=T0 + timedelta(seconds=k / 50), header=header, values=row.tolist())
            for k, row in enumerate(freq)]


def test_the_module_reports_islands_by_station_once_a_second():
    _, freq = islanding_test_case_1()
    module = IslandingDetectionModule()
    outputs = [message for frame in frames(freq[: 50 * 45]) for message in module.run(frame)]
    published = [message for message in outputs if isinstance(message, IslandingDetectionResult)]
    # Nothing until the 10 s window fills, then one result a second.
    assert 34 <= len(published) <= 36
    first, last = published[0].result, published[-1].result
    assert (first.islands, first.status) == ([], "OK")
    assert [sorted(island) for island in last.islands] == [["s2", "s3", "s5"]]
    assert last.status == "Emergency"


def test_reset_forgets_the_window():
    _, freq = islanding_test_case_1()
    module = IslandingDetectionModule(window_length_s=1.0)
    stream = frames(freq[:100])
    assert any(module.run(frame) for frame in stream)
    module.reset()
    assert module.run(stream[0]) == []


def test_an_island_raises_an_alarm_that_clears_after_the_hold():
    """Islands at 20-60 s and 130-150 s: two alarms, each issued as its island
    forms and cleared once the window has been whole for ``alarm_hold_s``."""
    _, freq = islanding_test_case_1()
    module = IslandingDetectionModule(alarm_hold_s=15)
    alarms = [(k / 50, message) for k, frame in enumerate(frames(freq))
              for message in module.run(frame) if isinstance(message, AlarmEvent)]
    assert [message.type for _, message in alarms] == ["init", "not_critical", "init", "not_critical"]
    (issued, first), (cleared, end_of_first), (reissued, second), _ = alarms
    assert 20 < issued < 25 and 130 < reissued < 135
    assert 60 + 15 < cleared < 60 + 10 + 15 + 2  # the island leaves the 10 s window, then the hold
    assert first.alarm_uuid == end_of_first.alarm_uuid != second.alarm_uuid
    assert first.app == module.identity
