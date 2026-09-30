# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``/api/errors/ws?client_id=``: this client's error notices. What the hub
kept for the client first, then each new one."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket

from pswamp_core.util.tasks import cancel_and_wait
from pswamp_web.pump import wait_for_disconnect
from pswamp_web.wire import read_client_id, send_state

from .hub import HUB

router = APIRouter()


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    client_id = read_client_id(ws)
    if client_id is None:
        await ws.close(code=1008)
        return
    await ws.accept()
    with HUB.tray(client_id) as notices:
        for notice in HUB.recent(client_id):
            await send_state(ws, notice)

        async def push() -> None:
            while True:
                await send_state(ws, await notices.get())

        pusher = asyncio.create_task(push())
        try:
            await wait_for_disconnect(ws)
        finally:
            await cancel_and_wait(pusher, ignore=(Exception,))
