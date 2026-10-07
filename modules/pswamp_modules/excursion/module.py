# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``ExcursionModule``: a module chained onto another, which can pause the player.

It reads ``FrameStatsResult``, what ``FrameStatsModule`` publishes, so the two
form a chain: frame → frame stats → excursion. It reports whether the mean
frequency is outside a band around 50 Hz, and counts excursions.

Two commands go through it. ``AutoPauseCommand`` (from the page) turns
pausing on excursion on or off for this run. When it is on and the frequency
leaves the band, the module returns a ``PauseCommand`` beside its result: a
command is one more declared output, published on its topic as the web API
publishes it, and the player takes it.

Its messages are in ``pswamp_models.excursion``; what it reads, in
``pswamp_models.frame_stats``.
"""

from __future__ import annotations

from pswamp_core.modules import Module
from pswamp_models.excursion import AutoPauseCommand, Excursion, ExcursionResult
from pswamp_models.frame_stats import FrameStatsResult
from pswamp_models.player import PauseCommand

__all__ = ["ExcursionModule"]

NOMINAL_HZ = 50.0
BAND_HZ = 0.005


class ExcursionModule(Module):
    name = "excursion"
    inputs = (FrameStatsResult,)
    outputs = (ExcursionResult, PauseCommand)
    commands = (AutoPauseCommand,)

    def __init__(self) -> None:
        super().__init__()
        self.parameters = {"nominal_hz": NOMINAL_HZ, "band_hz": BAND_HZ}
        self.auto_pause = False
        self.excursions = 0
        self._in_band = True
        self._deviation: float | None = None

    def process(self, stats: FrameStatsResult) -> Excursion | list[Excursion | PauseCommand] | None:
        mean = stats.result.mean_frequency_hz
        if mean is None:
            return None
        self._deviation = mean - NOMINAL_HZ
        in_band = abs(self._deviation) <= BAND_HZ
        left = self._in_band and not in_band
        if left:
            self.excursions += 1
        self._in_band = in_band
        if left and self.auto_pause:
            return [self._state(), PauseCommand()]
        return self._state()

    def handle(self, command: AutoPauseCommand) -> Excursion:
        self.auto_pause = command.enabled
        return self._state()

    def _state(self) -> Excursion:
        return Excursion(
            in_band=self._in_band,
            deviation_hz=self._deviation,
            band_hz=BAND_HZ,
            excursions=self.excursions,
            auto_pause=self.auto_pause,
        )
