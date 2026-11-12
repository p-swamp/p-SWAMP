# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The alarm list's state machine, fed the alarm events modules publish.

The desktop package has its equivalent in ``coordination.AlarmMonitor``, but there
the useful logic sits inside a ``for message in consumer:`` loop over a Kafka
topic, so it cannot be reused without a broker. What is reimplemented here is only
the state machine part; the shapes match, so folding it back as the pure half of
that class is mechanical.
"""

import time
from collections import OrderedDict

from .wire import Alarm, AlarmEvent

# How long an application may go unheard before its row is shown as stale. Same
# three seconds the Qt status table greys out after.
STALE_AFTER = 3.0


class AlarmStore:
    """Alarm lifecycle, driven by the events applications publish.

    The transitions are p-SWAMP's, from ``AlarmMonitor.run_alarm_consumer``:
    an "init" event opens an alarm as unseen, "not_critical" closes it out,
    and acknowledging or silencing it are operator actions from the UI.
    """

    _TRANSITIONS = {
        "init": "unseen",
        "not_critical": "not_critical",
        "acknowledge": "acknowledged",
        "silence": "silenced",
    }

    def __init__(self, limit: int = 200) -> None:
        self._alarms: OrderedDict[str, dict] = OrderedDict()
        self._limit = limit

    def handle(self, message: dict) -> None:
        """Apply one alarm event.

        Note the coercions. Upstream puts a ``uuid.UUID`` and a ``datetime``
        straight into this message, neither of which JSON can carry -- which is
        precisely why the streaming layer falls back to pickling. Normalising
        here keeps that problem contained rather than changing a message shape
        that existing consumers depend on.
        """
        alarm_id = str(message["uuid"])
        event_type = message.get("type", "user_message")
        time_stamp = message["time_stamp"]
        t = (
            time_stamp.timestamp()
            if hasattr(time_stamp, "timestamp")
            else float(time_stamp)
        )

        alarm = self._alarms.get(alarm_id)
        if alarm is None:
            alarm = {
                "uuid": alarm_id,
                "app_uuid": str(message.get("app", "")),
                "app_name": message.get("app_name", "unknown"),
                "t_start": t,
                "t_end": None,
                "status": "unseen",
                "events": [],
            }
            self._alarms[alarm_id] = alarm
            while len(self._alarms) > self._limit:
                self._alarms.popitem(last=False)

        alarm["events"].append(
            AlarmEvent(t=t, type=event_type, message=str(message.get("message", "")))
        )
        status = self._TRANSITIONS.get(event_type)
        if status is not None:
            alarm["status"] = status
        if event_type == "not_critical":
            alarm["t_end"] = t

    def annotate(self, alarm_id: str, event_type: str, message: str) -> bool:
        """Record an operator action. Returns False for an unknown alarm."""
        if alarm_id not in self._alarms:
            return False
        self.handle(
            {
                "uuid": alarm_id,
                "time_stamp": time.time(),
                "app": self._alarms[alarm_id]["app_uuid"],
                "app_name": self._alarms[alarm_id]["app_name"],
                "type": event_type,
                "message": message,
            }
        )
        return True

    def list(self) -> list[Alarm]:
        """Newest first, the order the Qt alarm overview shows them in."""
        return [Alarm(**alarm) for alarm in reversed(self._alarms.values())]
