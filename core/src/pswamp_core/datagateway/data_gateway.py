# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``DataGateway``: a run's data clients as named sources, one of them active.

    gateway.sources                     # ["sample", "live"], in declared order
    gateway.source, gateway.live        # the active source, and whether it is a live feed
    gateway.switch("live")              # another source is active from now on
    gateway.consume(start=t0)           # from t0 onwards: a seek
    gateway.consume(start=t0, end=t1)   # exactly [t0, t1): a chunk

One source at a time, and only an explicit switch changes it, so a stream
always has exactly one provider behind it. A client is opened on first use, so
a source nobody reads (a live feed on a client's own run) costs nothing.
Adapted from Louis Pauchet's test_pswamp draft, without its routing of one
stream across several clients.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from ..log import get_logger
from .data_client import DataClient
from .stream import DataStream
from .time_range import TimeRange

__all__ = ["DataGateway"]

logger = get_logger("pswamp_core.datagateway.gateway")


class DataGateway:
    """Named sources, one active.

    Args:
        clients: The sources, in order. The first is active unless ``active``
            names another.

    Raises:
        ValueError: No clients, two with one name, or ``active`` names none.
    """

    def __init__(self, clients: Sequence[DataClient], *, active: str | None = None) -> None:
        if not clients:
            raise ValueError("a gateway needs at least one data client")
        self.clients: dict[str, DataClient] = {}
        for client in clients:
            if client.name in self.clients:
                raise ValueError(f"two data clients are named {client.name!r}")
            self.clients[client.name] = client
        self._active = self._named(active) if active is not None else clients[0]
        self._opened: set[str] = set()

    @property
    def sources(self) -> list[str]:
        return list(self.clients)

    @property
    def active(self) -> DataClient:
        return self._active

    @property
    def source(self) -> str:
        return self._active.name

    @property
    def live(self) -> bool:
        """Whether the active source is a live feed."""
        return self._active.kind == "live"

    def kind(self, source: str) -> str:
        """``"history"`` or ``"live"``."""
        return self._named(source).kind

    def switch(self, source: str) -> DataClient:
        """Make ``source`` the active one. An open stream is the caller's to close."""
        self._active = self._named(source)
        logger.info("gateway switched to %s", source)
        return self._active

    async def coverage(self) -> TimeRange | None:
        """What the active source holds; ``None`` for a live feed. Raises what
        the client raises."""
        await self._open(self._active)
        return await self._active.coverage()

    async def consume(self, start: datetime | None = None, end: datetime | None = None) -> DataStream:
        """A stream over ``[start, end)`` of the active source."""
        await self._open(self._active)
        return DataStream(self._active, TimeRange(start, end))

    async def close(self) -> None:
        """Close every client that was opened."""
        for name in list(self._opened):
            self._opened.discard(name)
            try:
                await self.clients[name].close()
            except Exception as error:
                logger.error("data client %s failed to close: %s", name, error)

    async def _open(self, client: DataClient) -> None:
        if client.name not in self._opened:
            await client.open()
            self._opened.add(client.name)

    def _named(self, source: str) -> DataClient:
        client = self.clients.get(source)
        if client is None:
            raise ValueError(f"no source named {source!r}; the sources are {list(self.clients)}")
        return client
