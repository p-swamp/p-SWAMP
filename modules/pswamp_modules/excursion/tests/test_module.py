"""The excursion module: chained onto frame statistics, and able to pause the player."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pswamp_models.excursion import AutoPauseCommand, ExcursionResult
from pswamp_models.frame_stats import FrameStats, FrameStatsResult
from pswamp_models.player import PauseCommand
from pswamp_modules.excursion import ExcursionModule

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def stats_at(mean: float, seconds: float = 0.0) -> FrameStatsResult:
    body = FrameStats(n_stations=5, mean_frequency_hz=mean, min_frequency_hz=mean, max_frequency_hz=mean,
                      angle_spread_deg=0.0, mean_voltage_kv=400.0)
    return FrameStatsResult(timestamp=T0 + timedelta(seconds=seconds), app={"name": "frame-stats", "uuid": "u"}, result=body)


def test_the_excursion_module_counts_excursions_and_can_pause_the_player():
    module = ExcursionModule()
    assert module.run_one(stats_at(50.001)).result.in_band
    (answer,) = module.run_command(AutoPauseCommand(enabled=True))
    assert isinstance(answer, ExcursionResult) and answer.result.auto_pause
    left, pause = module.run(stats_at(50.008))  # leaving the band, with auto-pause on
    assert (left.result.in_band, left.result.excursions, left.result.auto_pause) == (False, 1, True)
    assert isinstance(pause, PauseCommand)
    assert len(module.run(stats_at(50.009))) == 1  # still out: no second excursion, no second pause
    module.run_command(AutoPauseCommand(enabled=False))
    module.run(stats_at(50.0))
    (back_out,) = module.run(stats_at(49.99))  # out again, auto-pause off: no pause
    assert back_out.result.excursions == 2
