# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""Serving one downstream socket: the part every page endpoint had written out.

A page endpoint is three things -- accept the socket, decide what to send, and then
run it. This module is the third, so that what is left in a page package is the
second, which is the only part that differs.

Two shapes of page, and both are here:

* **Ticker-driven** -- :func:`serve_ticks`. Read the state on a timer and send what
  is there. Used where there is nothing to react to: a measurement stream
  (``time_window``, ``phasors``) or a table whose interesting case is something
  *not* arriving (``app_status``, where "stale" is the absence of a report). It is
  what keeps a 50 Hz sample stream from becoming 50 event-loop callbacks a second.
* **Event-driven** -- a queue woken with :func:`offer`, then :func:`serve_updates`.
  Send when there is something to send. Used for results and alarms
  (``islanding``, ``line_outage``), which arrive about once a second, or not at all
  while the grid is healthy.

Both end in :func:`wait_for_disconnect`, which the scaffold apps under ``src/``
use directly through ``shared.py`` -- they have no pusher of their own, but they
need the same receive loop for the same reason.
"""

import asyncio
import contextlib
from collections.abc import Callable
from typing import NamedTuple

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from .log import get_logger
from .wire import send_state

logger = get_logger("pswamp_web.pump")


async def wait_for_disconnect(ws: WebSocket) -> None:
    """Hold the connection open until the client goes away.

    Every socket in this backend is downstream only: nothing a client sends up
    one is ever read as a command (those are POSTs). The receive loop is not
    vestigial even so — without a pending receive, a closed socket is noticed only
    on the next *send*, so a page that pushes rarely, or an idle client on a page
    that pushes on events, would linger for as long as the server had nothing to
    say.

    Returns rather than raises on any connection ending: an ordinary disconnect
    stays quiet, while an unexpected receive failure is logged before the
    caller's cleanup continues as ordinary control flow.
    """
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.warning("socket receive ended unexpectedly", exc_info=True)


async def _serve(ws: WebSocket, push: Callable[[], object]) -> None:
    """Run ``push`` as a task for exactly as long as the client is connected."""
    pusher = asyncio.create_task(push())
    try:
        await wait_for_disconnect(ws)
    finally:
        pusher.cancel()
        # The task is being cancelled from outside, so its CancelledError is
        # expected rather than an error; awaiting it is what makes sure it is
        # finished before the caller releases the pipeline it was reading.
        with contextlib.suppress(asyncio.CancelledError):
            await pusher


# --- ticker-driven pages ----------------------------------------------------


async def serve_ticks(
    ws: WebSocket,
    hz: float,
    build: Callable[[], BaseModel | None],
) -> None:
    """Send ``build()`` every 1/``hz`` seconds until the client disconnects.

    ``build`` returning ``None`` means "nothing new" and sends nothing, which is
    what lets a page whose window has not advanced cost nothing (see
    ``time_window``). It is called on the event loop, so it must not block: read a
    snapshot, don't compute.
    """
    interval = 1 / hz

    async def push() -> None:
        while True:
            message = build()
            if message is not None:
                await send_state(ws, message)
            await asyncio.sleep(interval)

    await _serve(ws, push)


# --- event-driven pages -----------------------------------------------------


class Event(NamedTuple):
    """One notification, as a push task sees it.

    ``topic`` says which of the queue's topics woke it, since a page may listen
    on several and they do not all mean the same thing. Both fields are ``None``
    for a nudge from a *command* — an operator action changes what a page shows
    without any application having published anything, so it has no topic and
    carries no payload (see ``grid_monitor.live.LiveGrid.nudge``).
    """

    topic: str | None = None
    payload: object = None


def offer(queue: asyncio.Queue, event: Event = Event()) -> None:
    """Wake a push task, or drop the notification if it is already behind.

    Dropping is safe *because* of how the pages are written: the message is built
    from the state when the task wakes, never from what is on the queue, so a lost
    notification costs latency and never content.
    """
    with contextlib.suppress(asyncio.QueueFull):
        queue.put_nowait(event)


async def serve_updates(
    ws: WebSocket,
    updates: asyncio.Queue,
    build: Callable[[Event | None], BaseModel | None],
) -> None:
    """Send on connect, then again on every notification, until disconnect.

    ``build`` is passed the :class:`Event` that woke the task, and ``None`` for
    the opening message — a page that does not care which topic fired takes the
    argument and ignores it.
    """

    async def push() -> None:
        opening = build(None)
        if opening is not None:
            await send_state(ws, opening)
        while True:
            message = build(await updates.get())
            if message is not None:
                await send_state(ws, message)

    await _serve(ws, push)
