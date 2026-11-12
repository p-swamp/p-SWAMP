"""Line outages: the branches of the live grid that carry no current, and when they stopped.

The web counterpart of the desktop's ``LineOutageDetectionApp``, which is the ``line-outage`` module
here (``modules/line-outage/``). Event-driven: the log is sent on connect, and again whenever the
module reports a change; the module's other results only say it is alive.
"""

from fastapi import APIRouter, WebSocket

from pswamp_web.pump import serve_updates

from ..live import LINE_OUTAGE, LIVE, accept

router = APIRouter()


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    if not await accept(ws):
        return
    with LIVE.updates(LINE_OUTAGE) as updates:
        await serve_updates(ws, updates, lambda _event: LIVE.outages)
