"""The excursion module: chained onto frame statistics, and able to pause the player."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pswamp_models.excursion import AutoPauseCommand
from pswamp_models.frame_stats import FrameStats, FrameStatsResult
from pswamp_models.player import PauseCommand
from pswamp_modules.excursion import ExcursionModule

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


class Recorder:
    def __init__(self) -> None:
        self.published: list = []

    def publish(self, message) -> None:
        self.published.append(message)


def stats_at(mean: float, seconds: float = 0.0) -> FrameStatsResult:
    body = FrameStats(n_stations=5, mean_frequency_hz=mean, min_frequency_hz=mean, max_frequency_hz=mean,
                      angle_spread_deg=0.0, mean_voltage_kv=400.0)
    return FrameStatsResult(timestamp=T0 + timedelta(seconds=seconds), app={"name": "frame-stats", "uuid": "u"}, result=body)


async def test_the_excursion_module_counts_excursions_and_can_pause_the_player():
    module, out = ExcursionModule(), Recorder()
    await module.setup(out)
    assert (await module.process(stats_at(50.001))).in_band
    await module.handle(AutoPauseCommand(enabled=True))
    left = await module.process(stats_at(50.008))
    assert (left.in_band, left.excursions, left.auto_pause) == (False, 1, True)
    await module.process(stats_at(50.009))  # still out: no second excursion
    assert [type(m) for m in out.published] == [PauseCommand]
    await module.handle(AutoPauseCommand(enabled=False))
    await module.process(stats_at(50.0))
    assert (await module.process(stats_at(49.99))).excursions == 2 and len(out.published) == 1
