# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""Line outage detection.

The web counterpart of p-SWAMP's ``LineOutageDetectionApp``, which watches the
current magnitude on every branch and reports the moment one stops carrying
current. The detector itself is upstream and unmodified; everything here is
transport.

Event-driven, and more so than islanding: ``run_analysis`` returns ``None``
unless a branch actually changed state, so a healthy grid produces no traffic at
all. There is nothing to poll and no ticker -- the client is sent the log on
connect, and again whenever it grows.

Note this application is the reason the recorded dataset carries current
channels. It reads ``i_Magnitude``, which the frequency- and voltage-based
applications ignore; a recording made without those channels leaves this
detector running happily and finding nothing, forever.
"""

from fastapi import APIRouter, WebSocket

from ..hub import LINE_OUTAGE_RESULT_TOPIC, Hub, connected_hub
from ..pump import event_queue, serve_updates
from ..wire import LineOutageLog

router = APIRouter()


def current_message(hub: Hub) -> LineOutageLog:
    store = hub.line_outages
    return LineOutageLog(
        app_uuid=store.app_uuid,
        app_name=store.app_name,
        window_length=store.window_length,
        events=store.list(),
        disconnected=store.disconnected(),
    )


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    async with connected_hub(ws) as hub:
        if hub is None:
            return
        # This client's own bus, so the listener only ever hears about this
        # client's replay. The log is re-read from the store on every wake-up
        # rather than carried on the queue, which is why a dropped notification
        # costs latency and never content -- and why the event itself is ignored.
        with event_queue(hub.bus, LINE_OUTAGE_RESULT_TOPIC) as updates:
            await serve_updates(ws, updates, lambda _event: current_message(hub))
