"""Which modules are analysing the live grid, and what they report; and the feed they read.

The web counterpart of the desktop's ``gui.app_monitoring.AppStatusMonitoringWidget``. A module's
row is its last result's status (each result says it, about once a second or more often); a module
that stops publishing goes stale, which is the absence of a message, so this is a ticker rather than
a subscription.
"""

import time

from fastapi import APIRouter, WebSocket
from pswamp_web.pump import serve_ticks
from pswamp_web.wire import AppStatusTable

from ..live import LIVE, accept

# Twice the modules' reporting rate, so a change shows within about half a second.
PUSH_HZ = 2

router = APIRouter()


def status_message() -> AppStatusTable:
    return AppStatusTable(apps=LIVE.statuses(), server_time=time.time(), feed=LIVE.feed_status())


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    if await accept(ws):
        await serve_ticks(ws, PUSH_HZ, status_message)
