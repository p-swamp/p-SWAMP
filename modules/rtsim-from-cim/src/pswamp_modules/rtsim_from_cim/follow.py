# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``Follower``: the graph exported as a TOPS model once, and kept up to date with LazyCIM's ``refresh``.

``changes()`` looks at the graph's version stamp (``pswamp_core.cim.GraphVersion``: one tiny query)
and, only when it moved, marks the profiles that change stale (SSH and SV), brings the export up to
date with LazyCIM's ``refresh`` (which reads those again and nothing else) and says what moved, as the
engine applies it: the switches that opened or closed (with switches as branches an open switch is
exported closed and listed in ``sim.ids["open_switches"]``, so that list is what changes), the lines
and transformers whose terminal was disconnected or connected again (their rows go or come back:
branch events too),
the values that moved (a load's P and Q), or, when other rows came or went, a whole new model. When
the stamp has not moved it reads nothing else.

``FollowerProcess`` runs one in a process of its own, over a shared store, and sends what changed
straight to the engine's process.
"""

from __future__ import annotations

import copy
import multiprocessing
import time

from lazycim.sim import get_exporter
from pswamp_core.cim import CimSettings, GraphVersion, connect_reader, open_store, refresh_expired

from .engine import EXPORT, Change
from .pmu import read_analogs

__all__ = ["Follower", "FollowerProcess"]

#: The rows that a terminal disconnected (or connected again) takes out of the export, or brings
#: back, and that a running simulation follows as an event.
BRANCHES = ("lines", "transformers")


class Follower:
    """``repo``, a reader's repository over the graph, exported (``EXPORT``) and followed when
    ``version`` (the graph's stamp, watched from before the export) says it changed. For one thread."""

    def __init__(self, repo, version: GraphVersion) -> None:
        self.version = version
        self.exporter = get_exporter("tops", repo, **EXPORT)
        #: The export, kept up to date in place: ``sim.model`` for TOPS, ``sim.ids`` row name -> mRID.
        self.sim = self.exporter.build()

    @property
    def open_switches(self) -> frozenset[str]:
        return frozenset(self.sim.ids.get("open_switches", {}))

    def changes(self) -> Change:
        """What the graph changed since the last call (or the build); empty when nothing did."""
        if not self.version.changed():
            return Change()
        refresh_expired(self.exporter.repo)
        before = self.open_switches
        delta = self.exporter.refresh()
        after = self.open_switches
        rows = [*delta.removed, *delta.added]
        if delta.rebuilt and rows and all(component in BRANCHES for component, _ in rows):
            # Only lines and transformers came or went: a terminal disconnected or connected again. A
            # running simulation follows that as a branch event, as it does a switch, and keeps its
            # transient; were it built again, it would start over at steady state, seconds later.
            def named(found, component):
                return frozenset(name for kind, name in found if kind == component)

            return Change(
                opened=(after - before) | named(delta.removed, "lines"),
                closed=(before - after) | named(delta.added, "lines"),
                transformers_out=named(delta.removed, "transformers"),
                transformers_in=named(delta.added, "transformers"),
                values=tuple(delta.changes),
                model=copy.deepcopy(self.sim.model),
                ids=copy.deepcopy(self.sim.ids),
                open_switches=after,
                reason="branches came back",
                live=True,
            )
        if delta.rebuilt:
            return Change(
                model=copy.deepcopy(self.sim.model),
                ids=copy.deepcopy(self.sim.ids),
                open_switches=after,
                reason=delta.reason,
            )
        return Change(opened=after - before, closed=before - after, values=tuple(delta.changes))


def _watch(control, changes, up, settings: CimSettings, poll: float) -> None:
    """The follower's process: export, say so, then look at the stamp every ``poll`` seconds and send
    what changed down ``changes``, until told to stop (anything on ``control``, or its end closing)."""
    try:
        version = GraphVersion(open_store(settings))  # watched from before the export
        repo = connect_reader(settings)
        follower = Follower(repo, version)
        up.send(("ready", follower.sim.model, follower.open_switches, follower.sim.ids, read_analogs(repo)))
    except Exception as error:  # noqa: BLE001 -- the caller raises it
        up.send(("error", error))
        return
    try:
        while True:
            started = time.monotonic()
            try:
                change = follower.changes()
                if change:
                    changes.send(change)
            except (BrokenPipeError, EOFError, OSError):
                raise
            except Exception as error:  # noqa: BLE001 -- a store down for a moment must not end the stream
                up.send(("warning", f"the graph could not be read, the simulation keeps its last state: {error}"))
            if control.poll(max(0.0, poll - (time.monotonic() - started))):
                return
    except (BrokenPipeError, EOFError, OSError, KeyboardInterrupt):
        return


class FollowerProcess:
    """A ``Follower`` of the graph ``settings`` names (a shared store: Oxigraph), in a process of its
    own: the export, and a look at the version stamp every ``poll`` seconds, refreshing the export
    when it moved. A refresh is a second or so of Python (results parsed into tables) that, in the
    server's process, would hold up everything else there, the frames on their way to the pages
    included; here it holds up nothing. What changed goes straight to the engine's process, down
    ``changes`` (the read end, for ``EngineProcess``). ``ready`` waits for the export;
    ``receive`` gives what the follower says, until it ends."""

    def __init__(self, settings: CimSettings, *, poll: float) -> None:
        context = multiprocessing.get_context("spawn")
        control_read, self._control = context.Pipe(duplex=False)
        #: The read end of the changes, for the engine's process to take over.
        self.changes, changes_write = context.Pipe(duplex=False)
        self._up, up_write = context.Pipe(duplex=False)
        self._process = context.Process(
            target=_watch,
            args=(control_read, changes_write, up_write, settings, poll),
            name="rtsim-follow",
            daemon=True,
        )
        self._process.start()
        for end in (control_read, changes_write, up_write):
            end.close()

    def ready(self) -> tuple:
        """Wait for the export (blocking: from a thread): its model, open switches, ids and the PMU
        Analogs. Raises what the follower could not get past."""
        message = self._receive()
        if message[0] != "ready":
            raise message[1] if message[0] == "error" else RuntimeError(f"the follower said {message!r}")
        return message[1:]

    def receive(self) -> str | None:
        """The follower's next warning (blocking: from a thread); ``None`` once it has ended."""
        kind, *rest = self._receive()
        return None if kind == "gone" else f"{rest[0]}"

    def _receive(self) -> tuple:
        try:
            return self._up.recv()
        except (EOFError, OSError):
            return ("gone", RuntimeError("the follower's process ended"))

    def close(self) -> None:
        try:
            self._control.send(None)
        except (BrokenPipeError, OSError):
            pass
        self._process.join(timeout=5)
        if self._process.is_alive():
            self._process.terminate()
        for end in (self._control, self._up):
            end.close()
