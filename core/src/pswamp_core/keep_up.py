# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""Falling behind, noticed and reported: ``KeepUp`` and ``KeepUpMonitor``.

A module reads a bounded ``DROP_OLDEST`` queue: right for a live stream, and
silent unless someone counts. Every message that crossed a transport carries
when it was sent (``pswamp_models.common.sent_at``). The monitor watches both, dropped
input and input age, and past a ``KeepUp`` policy publishes an ``ErrorEvent``:
once on falling behind, at most every ``report_every_s`` while behind, and once
on catching up. So it reaches the error tray, not only the log. The run's
outbox reports the same way when it has to drop what it cannot publish.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pswamp_models.common import ErrorEvent, sent_at

from .log import get_logger
from .util.time import utcnow

if TYPE_CHECKING:
    from pswamp_models.common import DataModel

    from .subscription import Sink, Subscription

__all__ = ["KeepUp", "KeepUpMonitor"]

logger = get_logger("pswamp_core.keep_up")


@dataclass(frozen=True)
class KeepUp:
    """When a consumer counts as behind: any dropped input, or input older
    than ``max_input_age_s`` when read. While behind, one report per
    ``report_every_s``; an interval with neither means it caught up."""

    max_input_age_s: float = 2.0
    report_every_s: float = 5.0


class KeepUpMonitor:
    """Judges one consumer against a ``KeepUp`` policy and reports into a sink.

    Args:
        source: The ``source`` on its reports (a module's name).
        what: The report's wording after the label, e.g. "is not keeping up with pmu.frame".
        policy: The thresholds; ``None`` reports nothing.
        label: Who the report names, if not ``source``.
    """

    def __init__(self, source: str, what: str, policy: KeepUp | None, *, label: str | None = None) -> None:
        self.source = source
        self.what = what
        self.policy = policy
        self.label = label or source
        self.reports = 0
        self.behind = False
        self._dropped_total = 0
        self._behind_since = self._last_report = 0.0
        self._dropped = 0
        self._oldest: float | None = None
        self._bad = False

    def observe(self, inputs: Subscription, message: DataModel, out: Sink) -> None:
        """One input read: count what the queue dropped since, and its age."""
        new_drops, self._dropped_total = inputs.dropped - self._dropped_total, inputs.dropped
        stamped = sent_at(message)
        self.note(out, new_drops, None if stamped is None else max(0.0, time.time() - stamped))

    def note(self, out: Sink, new_drops: int, age: float | None = None) -> None:
        """Judge ``new_drops`` and an input ``age``, and report per the policy."""
        if self.policy is None:
            return
        bad = new_drops > 0 or (age is not None and age > self.policy.max_input_age_s)
        self._dropped += new_drops
        if age is not None:
            self._oldest = age if self._oldest is None else max(self._oldest, age)
        self._bad = self._bad or bad
        now = time.monotonic()
        if not self.behind:
            if bad:
                self.behind, self._behind_since = True, now
                self._report(out, now, f"{self.label} {self.what}")
            else:
                self._reset(now)
        elif now - self._last_report >= self.policy.report_every_s:
            if self._bad:
                self._report(out, now, f"{self.label} {self.what} (behind for {now - self._behind_since:.0f} s)")
            else:
                self.behind = False
                self._report(out, now, f"{self.label} caught up after {now - self._behind_since:.0f} s behind")

    def _report(self, out: Sink, now: float, message: str) -> None:
        detail = f"{self._dropped} dropped"
        if self._oldest is not None:
            detail += f", oldest input read {self._oldest:.1f} s after it was sent"
        logger.warning("%s: %s", message, detail)
        self.reports += 1
        out.publish(ErrorEvent(timestamp=utcnow(), source=self.source, message=message, detail=detail))
        self._reset(now)

    def _reset(self, now: float) -> None:
        self._last_report, self._dropped, self._oldest, self._bad = now, 0, None, False
