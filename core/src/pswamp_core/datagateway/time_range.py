# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``TimeRange``: a half-open interval ``[start, end)``, UTC.

A ``None`` bound is open: ``start=None`` reaches back without limit, and
``end=None`` runs on (to the end of a recording, or for ever on a live feed).
Adapted from Louis Pauchet's test_pswamp draft.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..util.time import ensure_utc

__all__ = ["TimeRange"]


@dataclass(frozen=True)
class TimeRange:
    start: datetime | None = None
    end: datetime | None = None

    def __post_init__(self) -> None:
        if self.start is not None:
            object.__setattr__(self, "start", ensure_utc(self.start))
        if self.end is not None:
            object.__setattr__(self, "end", ensure_utc(self.end))
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError(f"TimeRange end {self.end.isoformat()} precedes start {self.start.isoformat()}")

    def contains(self, moment: datetime) -> bool:
        """Whether ``moment`` lies in ``[start, end)``."""
        moment = ensure_utc(moment)
        return (self.start is None or moment >= self.start) and (self.end is None or moment < self.end)
