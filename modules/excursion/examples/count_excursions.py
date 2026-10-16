"""Count frequency excursions over a synthetic series, with no server.

The excursion module reads frame statistics (``FrameStatsResult``, what the
frame-stats module publishes). Here the statistics are made up directly: a
mean frequency that drifts out of the ±5 mHz band around 50 Hz twice. With
auto-pause on, leaving the band also emits a ``PauseCommand``, which hosted
would pause the player; here it is simply printed. No server, no transport, no
event loop.

    uv run python modules/excursion/examples/count_excursions.py
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pswamp_models.excursion import AutoPauseCommand, ExcursionResult
from pswamp_models.frame_stats import FrameStats, FrameStatsResult
from pswamp_models.player import PauseCommand
from pswamp_modules.excursion import ExcursionModule

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
MEANS_HZ = [50.000, 50.002, 50.004, 50.007, 50.009, 50.003, 50.000, 49.998, 49.993, 49.990, 49.997, 50.001]


def stats_at(second: int, mean_hz: float) -> FrameStatsResult:
    body = FrameStats(
        n_stations=1,
        mean_frequency_hz=mean_hz,
        min_frequency_hz=mean_hz,
        max_frequency_hz=mean_hz,
        angle_spread_deg=0.0,
        mean_voltage_kv=400.0,
    )
    return FrameStatsResult(timestamp=T0 + timedelta(seconds=second), app={"name": "frame-stats", "uuid": "example"}, result=body)


def main() -> None:
    excursion = ExcursionModule()
    excursion.run_command(AutoPauseCommand(enabled=True))
    for second, mean_hz in enumerate(MEANS_HZ):
        for message in excursion.run(stats_at(second, mean_hz)):
            if isinstance(message, ExcursionResult):
                state = message.result
                band = "in band " if state.in_band else "OUT     "
                print(f"t={second:2d} s  {mean_hz:.3f} Hz  {band} deviation {state.deviation_hz:+.3f} Hz  excursions {state.excursions}")
            elif isinstance(message, PauseCommand):
                print("          -> PauseCommand (hosted, this pauses the player)")
    print(f"{excursion.excursions} excursions")


if __name__ == "__main__":
    main()
