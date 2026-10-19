# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``EngineProcess``: the simulation, paced in real time, in a process of its own.

A TOPS step is many small numpy calls, each of which takes Python's interpreter lock back when it
returns; in the server every other thread wants that lock too, and each call waits its turn
(Nordic44: four steps took 4 ms alone and 834 ms next to one busy thread). And the pacing itself
(sleep, step, build the frame, send it) needs the lock at every turn. So the whole real-time loop
runs here, in a process with an interpreter of its own: it keeps the schedule, steps, measures,
stamps each frame with its place in the schedule, and sends the values down a pipe. The server
only forwards them: when it is busy, a few frames arrive at once, but none is lost and none is late
on its own clock.

Two pipes, one each way. Down: what the graph changed (a ``Change``), applied before the next
frame's steps, and ``None`` to stop. Up: the frame layout's ``header`` (first, and again when the
model is built again), then ``("frame", timestamp, values)`` per frame, and ``("error", error)``
when the run cannot go on. And, when given, a third: ``changes``, the read end of a pipe whose
``Change``s come straight from a follower in another process (``follow.FollowerProcess``), so that
following the graph costs the server nothing.
"""

from __future__ import annotations

import multiprocessing
import queue
import threading
import time
from datetime import datetime, timedelta, timezone

from .engine import Change, SimEngine
from .pmu import Measured, pmu_layout, pmu_values

__all__ = ["EngineProcess", "MAX_LAG"]

#: Seconds behind the clock the loop catches up from; beyond, the lost time is dropped.
MAX_LAG = 0.25


class _Outbox:
    """What the loop sends up, sent by a thread of its own as lists of all that waited: the loop never
    waits on the pipe, and a reader that is slow for a moment gets the frames it missed in one go.
    ``close`` sends what is left, then stops the thread."""

    def __init__(self, up) -> None:
        self._up, self._queue = up, queue.SimpleQueue()
        self._thread = threading.Thread(target=self._run, name="rtsim-send", daemon=True)
        self._thread.start()

    def send(self, message: tuple) -> None:
        self._queue.put(message)

    def close(self) -> None:
        self._queue.put(None)
        self._thread.join(timeout=5)

    def _run(self) -> None:
        try:
            while True:
                batch = [self._queue.get()]
                while not self._queue.empty():
                    batch.append(self._queue.get_nowait())
                done = batch[-1] is None
                if batch := [message for message in batch if message is not None]:
                    self._up.send(batch)
                if done:
                    return
        except (BrokenPipeError, EOFError, OSError):
            return


def _serve(down, changes, up, model, open_switches, dt, rate, steps, analogs, ids) -> None:  # noqa: PLR0913
    """The engine process: ``_run``, with what it sends up flushed before the process ends."""
    up = _Outbox(up)
    try:
        _run(up, down, changes, model, open_switches, dt, rate, steps, analogs, ids)
    finally:
        up.close()


def _run(up, down, changes, model, open_switches, dt, rate, steps, analogs, ids) -> None:  # noqa: PLR0913
    """Build, then step in real time until told to stop, sending each frame up."""
    try:
        engine = SimEngine(model, open_switches=open_switches, dt=dt)
        layout = pmu_layout(analogs, engine, ids, rate)
    except Exception as error:  # noqa: BLE001 -- the caller raises it
        up.send(("error", error))
        return
    up.send(("header", layout.header))

    def apply(change: Change) -> None:
        nonlocal layout
        builds = engine.builds
        for done in engine.apply(change):
            up.send(("log", done))
        if engine.builds != builds and change.ids is not None:
            layout = pmu_layout(analogs, engine, change.ids, rate)
            up.send(("header", layout.header))

    period = 1.0 / rate
    origin, due = datetime.now(timezone.utc), time.monotonic()
    start = due
    try:
        while True:
            while down.poll():
                change = down.recv()
                if change is None:
                    return
                apply(change)
            try:
                while changes is not None and changes.poll():
                    apply(changes.recv())
            except (EOFError, OSError):  # the follower is gone: the simulation goes on as it is
                up.send(("log", "the graph is no longer followed"))
                changes = None
            due += period
            delay = due - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            elif -delay > MAX_LAG:  # far behind: drop the time rather than burst through it
                due = time.monotonic()
            snapshot = engine.step(steps)
            up.send(("frame", origin + timedelta(seconds=due - start), pmu_values(layout, snapshot)))
    except (BrokenPipeError, EOFError, KeyboardInterrupt):
        return
    except Exception as error:  # noqa: BLE001 -- the caller raises it
        up.send(("error", error))


class EngineProcess:
    """The simulation of ``model`` (with ``open_switches`` open), run in real time at ``rate`` frames per
    second of ``steps`` steps of ``dt``, measured at ``analogs`` (``ids`` is the export's
    ``sim.ids``). ``send`` a change, or have it read them from ``changes`` (a pipe's read end, which
    it takes over); ``receive`` what it sends up (blocking: from a thread)."""

    def __init__(
        self,
        model: dict,
        *,
        open_switches=(),
        dt: float,
        rate: float,
        steps: int,
        analogs: list[Measured],
        ids: dict,
        changes=None,
    ) -> None:
        context = multiprocessing.get_context("spawn")  # nothing of the server's state comes along
        down_read, self._down = context.Pipe(duplex=False)
        self._up, up_write = context.Pipe(duplex=False)
        self._process = context.Process(
            target=_serve,
            args=(down_read, changes, up_write, model, frozenset(open_switches), dt, rate, steps, analogs, ids),
            name="rtsim-engine",
            daemon=True,
        )
        self._process.start()
        down_read.close()
        up_write.close()
        if changes is not None:
            changes.close()  # the engine's process has its own

    def send(self, change: Change) -> None:
        self._down.send(change)

    def receive(self) -> list[tuple]:
        """What was sent up since the last call, at least one message (blocking: from a thread): each
        ``("header", h)``, ``("frame", t, values)``, ``("log", text)`` or ``("error", e)``, and
        ``("error", RuntimeError)`` when the process is gone. All at once, so that a busy server pays
        for one wake-up however many frames came meanwhile."""
        try:
            messages = self._up.recv()
            while self._up.poll():
                messages += self._up.recv()
            return messages
        except (EOFError, OSError):
            return [("error", RuntimeError("the simulation process ended"))]

    def close(self) -> None:
        try:
            self._down.send(None)
        except (BrokenPipeError, OSError):
            pass
        self._process.join(timeout=5)
        if self._process.is_alive():
            self._process.terminate()
        self._down.close()
        self._up.close()
