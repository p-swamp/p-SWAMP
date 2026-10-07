# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""Loop-side state built from what the application threads publish.

p-SWAMP has equivalents of both of these -- ``coordination.AlarmMonitor`` and
``gui.app_monitoring.AppStatusMonitoring`` -- but in both the useful logic sits
inside a ``for message in consumer:`` loop over a Kafka topic, so neither can be
reused without a broker. What is reimplemented here is only the state machine
part; the shapes match, so folding these back into upstream as the pure half of
those classes is mechanical.
"""

import re
import time
from collections import OrderedDict

import numpy as np

from .wire import Alarm, AlarmEvent, AppStatus, LineOutageEvent

# How long an application may go unheard before its row is shown as stale. Same
# three seconds the Qt status table greys out after.
STALE_AFTER = 3.0

# "I[L3244-6500]_Magnitude" -> "L3244-6500": the element a current channel
# measures. The same convention p-SWAMP's own ``models.line.Line`` relies on when
# it asks for the channel ``I[<line name>]``.
_MEASURED_ELEMENT = re.compile(r"\[([^\]]+)\]")


def island_groups(n_channels: int, raw_islands) -> list[np.ndarray]:
    """Group channel indices into ``[main system, island 1, island 2, ...]``.

    ``detect_islands`` reports only the groups that have *separated*: it sorts
    what it finds by size and drops the largest, on the grounds that the largest
    is the grid itself. So the main system is never in the result and has to be
    recovered as whatever is left over -- which is also what the Qt alarm view
    does. Shared by everything that needs island membership, so the subtraction
    is written once.
    """
    # Make the groups disjoint. detect_islands masks already-assigned channels
    # when it labels them but not when it appends them to the list it returns, so
    # a channel whose frequency is close enough to two references is reported in
    # both -- and subtracting the union then leaves a "main system" far smaller
    # than the set of stations actually still connected. Claiming each channel
    # for the first group that reports it restores the partition.
    #
    # This is a bug in p-SWAMP that belongs fixed upstream; it is compensated
    # here rather than in the core. See
    # doc/WIP-context-port-from-qt-to-web-frontend.md §4.5 and §11.
    islands, claimed = [], set()
    for island in raw_islands:
        fresh = [i for i in np.asarray(island, dtype=int).tolist() if i not in claimed]
        claimed.update(fresh)
        islands.append(np.asarray(fresh, dtype=int))

    main = np.setdiff1d(np.arange(n_channels), np.asarray(sorted(claimed), dtype=int))
    return [main, *islands]


class IslandStore:
    """Which island each station is currently in.

    Kept as loop-side state fed from the bus, the same way alarms and statuses
    are, so that a page wanting to colour something by island does not have to
    reach into the application thread for it.
    """

    def __init__(self) -> None:
        self.station_to_island: dict[str, int] = {}
        self._app = None

    def attach(self, app) -> None:
        """Bind the application whose channel selection the indices refer to."""
        self._app = app

    def handle(self, result: dict) -> None:
        payload = (result or {}).get("result")
        if not payload or self._app is None:
            return
        stations = np.asarray(self._app.tw.header["station"])
        groups = island_groups(len(stations), payload["islands"])
        self.station_to_island = {
            str(station): index
            for index, columns in enumerate(groups)
            for station in stations[columns]
        }


class LineOutageStore:
    """A log of branch connect/disconnect transitions.

    The detector publishes only when something changes -- it returns ``None``
    from ``run_analysis`` otherwise -- so there is no "current state" message to
    snapshot. What a page wants instead is the recent history, which is what
    this keeps.

    Bounded, like the alarm store: this is a demo replaying a 70 s loop, so
    without a cap the same four-line trip would accumulate an entry every time
    the recording comes round again.

    The log alone cannot say what is disconnected *now* once it has dropped its
    oldest entries, so that is tracked beside it -- which is what lets the grid
    view paint an open line without replaying history.
    """

    def __init__(self, limit: int = 100) -> None:
        self._limit = limit
        self._events: list[LineOutageEvent] = []
        self._disconnected: set[str] = set()
        self.app_uuid: str | None = None
        self.app_name: str | None = None
        self.window_length: float | None = None

    def handle(self, result: dict) -> None:
        payload = (result or {}).get("result")
        if not payload:
            return
        info = result.get("info") or {}
        self.app_uuid = str(info.get("uuid")) if info.get("uuid") else self.app_uuid
        self.app_name = info.get("app_name") or self.app_name
        self.window_length = (result.get("parameters") or {}).get(
            "window_length", self.window_length
        )
        t = float(payload["time_stamp"])
        for event in payload.get("events") or []:
            measurements = [str(x) for x in event["measurements"]]
            self._events.append(
                LineOutageEvent(
                    t=t,
                    kind=event["type"],
                    stations=[str(x) for x in event["stations"]],
                    measurements=measurements,
                )
            )
            elements = {
                match.group(1)
                for match in map(_MEASURED_ELEMENT.search, measurements)
                if match
            }
            if event["type"] == "disconnect":
                self._disconnected |= elements
            else:
                self._disconnected -= elements
        del self._events[: max(0, len(self._events) - self._limit)]

    # Above list() on purpose: that method shadows the builtin for the rest of
    # the class body, so a `list[...]` annotation below it would not evaluate.
    def disconnected(self) -> list[str]:
        """Elements carrying no current right now, by the name in their channel."""
        return sorted(self._disconnected)

    def list(self) -> list[LineOutageEvent]:
        """Newest first, matching the alarm overview's ordering."""
        return list(reversed(self._events))


class AppStatusStore:
    """Latest status per application."""

    def __init__(self) -> None:
        self._statuses: dict[str, dict] = {}

    def handle(self, message: dict) -> None:
        self._statuses[str(message["uuid"])] = {
            "app_name": message["app_name"],
            "status": message["status"],
            "t": float(message["time_stamp"]),
            "received_at": time.time(),
        }

    def table(self) -> list[AppStatus]:
        now = time.time()
        return [
            AppStatus(
                uuid=uuid,
                app_name=entry["app_name"],
                status=entry["status"],
                t=entry["t"],
                received_at=entry["received_at"],
                stale=(now - entry["received_at"]) > STALE_AFTER,
            )
            for uuid, entry in sorted(
                self._statuses.items(), key=lambda kv: kv[1]["app_name"]
            )
        ]


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
