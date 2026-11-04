# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The simulation's protection: what trips a line, as a relay would.

- **Overload**: a line end carrying more than ``pickup`` times its permanent current limit (the
  graph's ``CurrentLimit``, ``LiveTops.limit``) trips the line after an inverse time, the IEC
  standard inverse curve: ``t = tms * 0.14 / ((I / I_pickup) ** 0.02 - 1)``. The time is spent as
  the overload goes on, faster the more it is over, and starts over whenever it falls back under.
- **A fault and its clearing** (``FaultAndClearCommand``) are timed by the controller (``follow``),
  which sends the clearing to the engine to apply at the very time asked for.

The controller evaluates it on the state the engine sends, every time it looks at the graph: an
overload trips within that much of its time, never early.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

__all__ = ["Overload", "ProtectionSettings", "trip_time"]


@dataclass(frozen=True)
class ProtectionSettings:
    """``enabled``: whether overloads trip lines. ``pickup``: the multiple of a line's permanent limit
    above which it is over. ``tms``: the curve's time multiplier."""

    enabled: bool = True
    pickup: float = 1.0
    tms: float = 0.5


def trip_time(ratio: float, *, tms: float) -> float:
    """Seconds to trip at ``ratio`` times the pickup current, on the IEC standard inverse curve;
    infinite at or under it."""
    if ratio <= 1.0:
        return math.inf
    return tms * 0.14 / (ratio**0.02 - 1.0)


class Overload:
    """The overload relay of every line end: how much of its time each has spent."""

    def __init__(self, settings: ProtectionSettings) -> None:
        self.settings = settings
        self._spent: dict[tuple[str, int], float] = {}
        self._last: float | None = None

    def check(self, t: float, readings: Iterable[tuple[str, int, float, float]]) -> list[tuple[str, int, float]]:
        """At simulated time ``t``, the ends ``(line, end, amperes, limit)`` that trip now, as
        ``(line, end, ratio to the pickup current)``; each starts over once tripped."""
        dt = 0.0 if self._last is None else max(0.0, t - self._last)
        self._last = t
        tripped = []
        for line, end, amperes, limit in readings:
            ratio = amperes / (self.settings.pickup * limit)
            if ratio <= 1.0:
                self._spent.pop((line, end), None)
                continue
            spent = self._spent.get((line, end), 0.0) + dt / trip_time(ratio, tms=self.settings.tms)
            if spent >= 1.0:
                tripped.append((line, end, ratio))
                self._spent.pop((line, end), None)
            else:
                self._spent[(line, end)] = spent
        return tripped

    def forget(self) -> None:
        """Start every relay over: a model built again is a grid at steady state."""
        self._spent.clear()
        self._last = None
