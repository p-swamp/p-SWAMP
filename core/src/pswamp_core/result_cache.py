# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``ResultCache``: results already computed for a recording, kept to show again.

    cache = ResultCache()
    cache.put("sample", result)                 # under the result's own class and data timestamp
    cache.at("sample", RollingMeanResult, t)    # the result for instant t, or None

A module with a window publishes nothing while the window fills, so a client
seeking back over a part already played would wait for results that were
computed moments ago. A run puts those results here and reads them back at
its cursor (``pswamp_core.pipeline``).

- **Keyed by what a result is about**: the source it was computed from, its
  class, and its data timestamp. Not by client, so one client's results serve
  every client on the same recording. That is only right for a module whose
  results are the same for everyone (``Module.cache_results``).
- **A result stands until the next one is due.** ``at(t)`` gives the newest
  result at or before ``t`` if ``t`` is less than one result interval after
  it: what a page would have been showing at ``t``. The interval is the
  smallest spacing seen between consecutive results of one stream. Until one
  is known, only an exact timestamp matches. Past a gap in the results there
  is no answer rather than an old one.
- **Bounded**: at most ``max_entries``, the oldest-put dropped first.
- **In memory, in this process.** Empty after a restart, and not shared
  between server replicas.

It decides nothing about validity. Whoever calls ``put`` vouches for the
result; the run only puts results a module published after its warm-up, from
a stream it knows to be a recording.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right, insort
from collections import deque
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from .messages.results import ResultEnvelope

__all__ = ["DEFAULT_MAX_ENTRIES", "ResultCache"]

#: 30 to 60 MB of results, by their size. One entry measured 2.9 KB of the
#: process's memory for a small result (rolling-frequency's, 280 bytes as
#: JSON) and 5.8 KB for one naming 44 stations in its parameters. Memory
#: grows by that much per result up to the cap, then stays level. At one
#: result per frame at 10 Hz the cap is 17 minutes of a recording; at one a
#: second, 2.8 hours.
DEFAULT_MAX_ENTRIES = 10_000

R = TypeVar("R", bound="ResultEnvelope")

_Key = tuple[str, type]

#: How many streams a shelf remembers the last result of. Several clients put
#: into one shelf at once, each from a stream of its own.
_STREAMS_REMEMBERED = 64


class _Shelf:
    """The results of one class for one source, in time order."""

    __slots__ = ("by_time", "interval", "last_of_stream", "times")

    def __init__(self) -> None:
        self.times: list[datetime] = []
        self.by_time: dict[datetime, ResultEnvelope] = {}
        #: The smallest spacing seen between consecutive results of one stream.
        self.interval: timedelta | None = None
        #: Per stream, the timestamp of its result put last; newest stream last.
        self.last_of_stream: dict[str, datetime] = {}


class ResultCache:
    """Results by source, class and data timestamp. See the module docstring."""

    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self.max_entries = max_entries
        self._shelves: dict[_Key, _Shelf] = {}
        #: Every entry in the order it was first put, for dropping the oldest.
        self._order: deque[tuple[_Key, datetime]] = deque()

    def __len__(self) -> int:
        return len(self._order)

    def put(self, source: str, result: ResultEnvelope) -> None:
        """Keep ``result`` as ``source``'s result of its class for its timestamp.
        A result already held for that instant is replaced."""
        key = (source, type(result))
        shelf = self._shelves.get(key)
        if shelf is None:
            shelf = self._shelves[key] = _Shelf()
        at = result.timestamp
        if result.stream is not None:
            before = shelf.last_of_stream.pop(result.stream, None)
            if before is not None and at > before and (shelf.interval is None or at - before < shelf.interval):
                shelf.interval = at - before
            shelf.last_of_stream[result.stream] = at
            if len(shelf.last_of_stream) > _STREAMS_REMEMBERED:
                del shelf.last_of_stream[next(iter(shelf.last_of_stream))]
        if at not in shelf.by_time:
            insort(shelf.times, at)
            self._order.append((key, at))
        shelf.by_time[at] = result
        while len(self._order) > self.max_entries:
            self._drop_oldest()

    def at(self, source: str, cls: type[R], instant: datetime) -> R | None:
        """``source``'s result of ``cls`` for ``instant``: the newest one at or
        before it, if ``instant`` is less than one result interval later."""
        shelf = self._shelves.get((source, cls))
        if shelf is None:
            return None
        index = bisect_right(shelf.times, instant) - 1
        if index < 0:
            return None
        found = shelf.times[index]
        if found != instant and (shelf.interval is None or instant - found >= shelf.interval):
            return None
        return shelf.by_time[found]  # type: ignore[return-value]

    def clear(self) -> None:
        self._shelves.clear()
        self._order.clear()

    def _drop_oldest(self) -> None:
        key, at = self._order.popleft()
        shelf = self._shelves[key]
        del shelf.by_time[at]
        del shelf.times[bisect_left(shelf.times, at)]
        if not shelf.times:
            del self._shelves[key]
