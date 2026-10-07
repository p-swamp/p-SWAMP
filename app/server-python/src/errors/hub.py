# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``ErrorHub``: the process's error notices, per client.

``publish`` turns an ``ErrorEvent`` into an ``ErrorNotice`` for a client, logs
it, keeps the last few (so a reload still shows a failure that came just
before it), and hands it to every tray socket that client has open. In memory
and bounded; nothing is persisted. Imports nothing from ``shared``, which
imports this.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from collections.abc import Iterator
from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from pswamp_models.common import ErrorEvent
from pswamp_web.log import get_logger
from pswamp_web.sessions import SessionRegistry

__all__ = ["HUB", "ErrorHub", "ErrorNotice"]

logger = get_logger("errors")


class ErrorNotice(BaseModel):
    """An ``ErrorEvent`` from one of the client's runs, with the app it came from."""

    type: Literal["state"] = "state"
    id: str = Field(description="Unique per notice: the tray dismisses and de-duplicates by it.")
    app: str = Field(description="The app whose pipeline it came from, e.g. 'pmu-test-streamer'.")
    source: str = Field(description="Who saw it: 'player', or a module's name.")
    message: str = Field(description="One line for a person.")
    detail: str | None = Field(default=None, description="The cause, e.g. 'Type: text'.")
    request_id: str | None = Field(default=None, description="The command it answers, if any.")
    timestamp: datetime = Field(description="When the failure was seen.")


class ErrorHub:
    def __init__(self, keep: int = 20) -> None:
        self._keep = keep
        self._recent: dict[str, deque[ErrorNotice]] = {}
        self._trays: SessionRegistry[asyncio.Queue[ErrorNotice]] = SessionRegistry()

    def publish(self, client_id: str, app: str, event: ErrorEvent) -> ErrorNotice:
        notice = ErrorNotice(
            id=uuid4().hex,
            app=app,
            source=event.source,
            message=event.message,
            detail=event.detail,
            request_id=event.request_id,
            timestamp=event.timestamp,
        )
        logger.error("client %s: %s/%s: %s (%s)", client_id, app, event.source, event.message, event.detail)
        self._recent.setdefault(client_id, deque(maxlen=self._keep)).append(notice)
        for tray in self._trays.of(client_id):
            with contextlib.suppress(asyncio.QueueFull):
                tray.put_nowait(notice)
        return notice

    def recent(self, client_id: str) -> list[ErrorNotice]:
        return list(self._recent.get(client_id, ()))

    @contextlib.contextmanager
    def tray(self, client_id: str) -> Iterator[asyncio.Queue[ErrorNotice]]:
        """A queue of this client's notices, for as long as its socket lives."""
        queue: asyncio.Queue[ErrorNotice] = asyncio.Queue(maxsize=64)
        with self._trays.registered(client_id, queue):
            yield queue


#: The process's hub: the forwarders publish into it, the errors socket reads it.
HUB = ErrorHub()
