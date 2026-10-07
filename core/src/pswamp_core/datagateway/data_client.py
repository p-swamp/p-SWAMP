# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``DataClient``: the contract a data source implements.

A client is **one source**, of one of two kinds:

- ``history``: holds a range of records (a recording, a store). ``coverage``
  says which; ``consume`` yields the records in a requested range and stops.
  The player replays it, and can seek.
- ``live``: a feed. ``coverage`` is ``None``; ``consume`` yields records as
  they arrive, from now, until the range's end or for ever.

``consume`` must yield ``model`` records with UTC timestamps, in timestamp
order, inside the requested range; closing the iterator early must release
whatever it holds. ``pswamp_core.testing.DataClientConformance`` checks all of
this.

A client imports only ``pswamp_core``, so a deployment can write its own
outside this repo. It is configured from the environment like any
``Configurable``: it declares ``env_settings``, and ``from_env(name)`` reads
``{NAME}_{SETTING}``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, ClassVar, Literal

from pswamp_models.pmu import PmuFrame

from ..settings import Configurable

if TYPE_CHECKING:
    from pswamp_models.common import DataModel

    from .time_range import TimeRange

__all__ = ["DataClient"]


class DataClient(Configurable, ABC):
    """One data source. Subclass it; see the module docstring for the contract."""

    #: What the client is: a seekable history, or a live feed.
    kind: ClassVar[Literal["history", "live"]]
    #: The message class it serves.
    model: ClassVar[type[DataModel]] = PmuFrame

    def __init__(self, name: str) -> None:
        self.name = name

    async def open(self) -> None:
        """Acquire resources (a connection, a ticker). The gateway calls it
        once, before the first ``coverage`` or ``consume``."""

    async def close(self) -> None:
        """Release them."""

    async def coverage(self) -> TimeRange | None:
        """The range a history holds, ``[first, end)``; ``None`` for a live
        feed, or a history holding nothing."""
        return None

    @abstractmethod
    def consume(self, time_range: TimeRange) -> AsyncIterator[DataModel]:
        """Yield the records in ``time_range``, in order."""
