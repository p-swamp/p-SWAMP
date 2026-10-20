# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""Keeping every reader's repository up to date, so that no module has to.

**One watch per store, per process** (``GraphWatch.of``). It looks at the version stamp
(``GraphVersion.changed``: one tiny query) every ``POLL`` seconds, in a thread of its own, and
counts the changes it saw: its ``generation``. However many modules read the store, and however
fast their inputs come, the store is asked once per ``POLL``.

**Each repository holds a ``Freshness``** (``GraphWatch.attach``): the generation it last caught up
with. Before each call into a module, the module asks ``stale()``, which compares two integers and
reads nothing, and only when the graph changed ``catch_up()`` marks what the repository holds of the
profiles that change stale (``refresh_expired``), so its next read sees the edit. A module never sees
any of this (``Module.cim_repo``, ``Module.cim_changed``).

A repository attaches before its first read, so a write in between is seen at the next poll: at worst
it reads again what it already had, never misses an edit. An edit reaches a module at its first call
after the next poll: ``POLL`` plus the gap to that call, at most.

The thread only asks the store and moves an integer on: it touches no event loop and no repository.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from ..log import get_logger
from .store import GraphVersion, Store, refresh_expired

__all__ = ["POLL", "Freshness", "GraphWatch", "close_watches"]

logger = get_logger("pswamp_core.cim")

#: How often a watch looks at the stamp, seconds (``PSWAMP_CIM_POLL``).
POLL = float(os.environ.get("PSWAMP_CIM_POLL", "") or 0.2)
#: How often a watch whose store fails says so, seconds.
_WARN_EVERY = 30.0


class GraphWatch:
    """The changes to one store, as this process sees them (see the module). Made by ``of``."""

    def __init__(self, store: Store, *, poll: float) -> None:
        self.store = store
        self.poll = poll
        #: How many changes the watch has seen: only ever moves on.
        self.generation = 0
        self._version = GraphVersion(store)  # from before any repository attached reads
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._watch, name=f"cim-watch {store.backend.name}", daemon=True)
        self._thread.start()

    @classmethod
    def of(cls, store: Store) -> GraphWatch:
        """The process's watch on ``store`` (on its backend: a script's ``Store.of(repo)`` gets one of
        its own), started on first use. It asks the store for the stamp: not on an event loop."""
        with _watches_lock:
            watch = _watches.get(id(store.backend))  # the watch keeps its backend, so the id stays its own
            if watch is None:
                watch = _watches[id(store.backend)] = cls(store, poll=POLL)
            return watch

    def attach(self, repo: Any) -> Freshness:
        """``repo``'s view of this watch, caught up with what it has seen so far."""
        return Freshness(repo, self)

    def _watch(self) -> None:
        warned = 0.0
        while not self._stop.wait(self.poll):
            try:
                if self._version.changed():
                    self.generation += 1
            except Exception as error:  # a store down for a moment must not end the watch
                if time.monotonic() - warned > _WARN_EVERY:
                    warned = time.monotonic()
                    logger.warning("cannot look at the CIM graph's version in %s: %s", self.store.backend.name, error)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)


class Freshness:
    """What one repository has caught up with (see the module). For the repository's own thread."""

    def __init__(self, repo: Any, watch: GraphWatch) -> None:
        self.repo = repo
        self.watch = watch
        self.seen = watch.generation

    def stale(self) -> bool:
        """Whether the graph changed since the last catch-up. Reads nothing."""
        return self.watch.generation != self.seen

    def catch_up(self) -> bool:
        """When stale, mark what the repository holds of the profiles that change stale, so its next
        read reads them again. Whether it was. Reads nothing."""
        now = self.watch.generation
        if now == self.seen:
            return False
        refresh_expired(self.repo)
        self.seen = now
        return True


_watches: dict[int, GraphWatch] = {}
_watches_lock = threading.Lock()


def close_watches() -> None:
    """Stop every watch of the process (for a test)."""
    with _watches_lock:
        watches = list(_watches.values())
        _watches.clear()
    for watch in watches:
        watch.close()
