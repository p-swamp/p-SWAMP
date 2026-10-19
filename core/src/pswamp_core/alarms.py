# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``AlarmRaiser``: when a module's status raises an alarm, and when it clears.

The desktop package's ``AlarmHandler`` (``pswamp.app_templates.status_reporting``)
without its I/O, renamed because it no longer sends anything: a module calls
``update`` with its status after each assessment and publishes the
``AlarmEvent`` it gets back, if any, beside its result. Declare ``AlarmEvent``
in the module's ``outputs`` for that. (Handling an alarm, in the operator's
sense, belongs to whatever keeps the alarm list.)

- A status in ``alarm_on`` issues an alarm (``init``), unless one is already
  active: a lasting emergency is one alarm, not one per assessment.
- Once the status has been out of ``alarm_on`` for more than ``hold_s``
  seconds, the active alarm is cleared (``not_critical``). An emergency that
  flickers on and off within that time stays the same alarm.

Time is the assessment's timestamp, never the wall clock, so a replay raises
the alarms the live feed did.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from uuid import uuid4

from pswamp_models.common import AlarmEvent, AppIdentity, AppStatus

__all__ = ["AlarmRaiser"]


class AlarmRaiser:
    def __init__(self, app: AppIdentity, *, alarm_on: Collection[AppStatus] = ("Emergency",), hold_s: float = 15.0):
        self.app = app
        self.alarm_on = frozenset(alarm_on)
        self.hold_s = hold_s
        self.reset()

    def reset(self) -> None:
        """Forget the active alarm: the stream it came from is gone."""
        self.active: str | None = None  # the active alarm's uuid
        self._last_critical: datetime | None = None

    def update(self, status: AppStatus, timestamp: datetime) -> AlarmEvent | None:
        """The event ``status`` at ``timestamp`` raises, or ``None``."""
        if status in self.alarm_on:
            self._last_critical = timestamp
            if self.active is not None:
                return None
            self.active = uuid4().hex
            return self._event("init", status, timestamp, "Alarm issued.")
        if self.active is not None and (timestamp - self._last_critical).total_seconds() > self.hold_s:
            event = self._event("not_critical", status, timestamp, "Alarm not critical anymore.")
            self.active = None
            return event
        return None

    def _event(self, type_, status: AppStatus, timestamp: datetime, message: str) -> AlarmEvent:
        return AlarmEvent(
            timestamp=timestamp, alarm_uuid=self.active, app=self.app, type=type_, status=status, message=message
        )
