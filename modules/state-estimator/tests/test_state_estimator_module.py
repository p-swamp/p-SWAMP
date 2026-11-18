"""The State Estimator module, bottom up: the analysis, then the module around it."""

from datetime import datetime, timezone

from pswamp_models.state_estimator import StateEstimatorResult
from pswamp_models.pmu import PmuFrame, PmuHeader
from pswamp_modules.state_estimator import StateEstimatorModule, highest_frequency


def test_picks_the_station_with_the_highest_frequency():
    assert highest_frequency(["a", "b", "c"], [49.9, 50.1, 50.0]) == ("b", 50.1)
    assert highest_frequency(["a", "b"], [None, 49.8]) == ("b", 49.8)
    assert highest_frequency(["a"], [None]) is None


def frame(values: list[float | None]) -> PmuFrame:
    n = len(values)
    header = PmuHeader(station=[f"s{i}" for i in range(n)], channel=["f"] * n, measurement=["f"] * n,
                       units=["Hz"] * n, data_rate=50.0)
    return PmuFrame(mRID="test", timestamp=datetime.now(timezone.utc), header=header, values=values)


def test_the_module_reads_the_frequency_columns():
    result = StateEstimatorModule().run_one(frame([49.9, 50.1, None]))
    assert isinstance(result, StateEstimatorResult)
    assert (result.result.station, result.result.frequency_hz) == ("s1", 50.1)
    assert StateEstimatorModule().run(frame([None])) == []  # nothing to publish
