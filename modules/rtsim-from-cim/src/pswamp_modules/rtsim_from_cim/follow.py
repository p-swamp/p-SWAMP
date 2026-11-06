# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``Controller``: the graph as LazyCIM's ``LiveTops``, steering the simulation in the engine's process.

``LiveTops`` exports the graph as a TOPS model, builds a shadow of the system the engine steps, and,
when the graph changes, decides what that means for a running simulation: a switch opened, a line
disconnected, a load's power or a machine's set-point moved, or a model to build again. Through a
``RemoteRunner`` (``runner``) each of those goes to the engine as a message, and the engine's state
comes back for ``LiveTops`` to read.

``changes()`` looks at the graph's version stamp (``pswamp_core.cim.GraphVersion``: one tiny query)
and, only when it moved, marks the profiles that change stale (SSH and SV) and has ``LiveTops``
follow the graph (LazyCIM's ``refresh``, which reads those again and nothing else). When the stamp
has not moved it reads nothing else.

``ControllerProcess`` runs one in a process of its own, over a shared store: a refresh is a second
or so of Python, which would hold up everything else in the server's process.
"""

from __future__ import annotations

import multiprocessing
import time
from collections.abc import Callable

from lazycim.sim.tops_live import LiveTops
from pswamp_core.cim import CimSettings, GraphVersion, connect_reader, open_store, refresh_expired

from .engine import EXPORT
from .pmu import read_analogs
from .runner import RemoteRunner, follow

__all__ = ["Controller", "ControllerProcess"]


class Controller:
    """``repo``, a reader's repository over the graph, simulated by ``LiveTops`` (exported with
    ``EXPORT``, stepped every ``dt`` simulated seconds) and followed when ``version`` (the graph's
    stamp, watched from before the export) says it changed. For one thread."""

    def __init__(self, repo, version: GraphVersion, *, dt: float) -> None:
        self.version = version
        self.live = LiveTops.from_repo(repo, dt=dt, **EXPORT)
        self.runner: RemoteRunner | None = None

    @property
    def sim(self):
        """The export, kept up to date: ``sim.model`` for TOPS, ``sim.ids`` row name -> mRID."""
        return self.live.sim

    def attach(self, send: Callable[[tuple], None]) -> None:
        """Steer the engine at the other end of ``send``, which runs ``sim.model`` as it is now."""
        self.runner = RemoteRunner(self.live, send)

    def receive(self, message: tuple) -> None:
        """What the engine sent: its state, each frame."""
        self.runner.receive(message)

    def changes(self) -> list[str]:
        """Follow what the graph changed since the last call; say what was done, one line each."""
        if not self.version.changed():
            return []
        refresh_expired(self.live.exporter.repo)
        return follow(self.live, self.runner)


def _watch(control, link, up, settings: CimSettings, poll: float, dt: float) -> None:
    """The controller's process: export, say so, then take the engine's state as it comes and look at
    the stamp every ``poll`` seconds, until told to stop (anything on ``control``, or its end closing)."""
    try:
        version = GraphVersion(open_store(settings))  # watched from before the export
        repo = connect_reader(settings)
        controller = Controller(repo, version, dt=dt)
        controller.attach(link.send)
        up.send(("ready", controller.sim.model, controller.sim.ids, read_analogs(repo)))
    except Exception as error:  # noqa: BLE001 -- the caller raises it
        up.send(("error", error))
        return
    try:
        while True:
            started = time.monotonic()
            while link.poll():
                controller.receive(link.recv())
            try:
                for said in controller.changes():
                    up.send(("log", said))
            except (BrokenPipeError, EOFError, OSError):
                raise
            except Exception as error:  # noqa: BLE001 -- a store down for a moment must not end the stream
                up.send(("warning", f"the graph could not be followed, the simulation keeps its last state: {error}"))
            if control.poll(max(0.0, poll - (time.monotonic() - started))):
                return
    except (BrokenPipeError, EOFError, OSError, KeyboardInterrupt):
        return


class ControllerProcess:
    """A ``Controller`` of the graph ``settings`` names (a shared store: Oxigraph), in a process of its
    own: ``LiveTops`` and a look at the version stamp every ``poll`` seconds. It steers the engine's
    process through ``link`` (the engine's end of a duplex pipe, for ``EngineProcess``). ``ready``
    waits for the export; ``receive`` gives what the controller says, until it ends."""

    def __init__(self, settings: CimSettings, *, poll: float, dt: float) -> None:
        context = multiprocessing.get_context("spawn")
        control_read, self._control = context.Pipe(duplex=False)
        #: The engine's end of the link, for the engine's process to take over.
        self.link, ours = context.Pipe()
        self._up, up_write = context.Pipe(duplex=False)
        self._process = context.Process(
            target=_watch,
            args=(control_read, ours, up_write, settings, poll, dt),
            name="rtsim-follow",
            daemon=True,
        )
        self._process.start()
        for end in (control_read, ours, up_write):
            end.close()

    def ready(self) -> tuple:
        """Wait for the export (blocking: from a thread): its model, ids and the PMU Analogs. Raises what
        the controller could not get past."""
        message = self._receive()
        if message[0] != "ready":
            raise message[1] if message[0] == "error" else RuntimeError(f"the controller said {message!r}")
        return message[1:]

    def receive(self) -> tuple[str, str] | None:
        """The controller's next ``("log" | "warning", text)`` (blocking: from a thread); ``None`` once it
        has ended."""
        kind, *rest = self._receive()
        return None if kind == "gone" else (kind, f"{rest[0]}")

    def _receive(self) -> tuple:
        try:
            return self._up.recv()
        except (EOFError, OSError):
            return ("gone", RuntimeError("the controller's process ended"))

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
