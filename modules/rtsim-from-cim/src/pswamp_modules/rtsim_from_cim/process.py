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

What the simulation does is decided elsewhere: by ``LiveTops``, in the controller (``follow``),
which reaches this process through a **link**, a duplex pipe. Down it come the events and inputs
to apply (``("event", ...)``, ``("input", ...)``), messages to apply at a later time on the build's
clock (``("at", t, messages)``: a fault's clearing, on time to the frame) and whole models to start
over from (``("build", n, model, ids)``), applied before the next frame's steps. Up it goes the state after
each frame (``("state", build, frame, t, y, v, rejected)``), only the latest one when the controller
is busy (a refresh takes a second): it reads the simulation from that, and is told which of the
events it sent could not be applied.

Two more pipes, with the server: down, ``None`` to stop; up, the frame layout's ``header`` (first,
and again when the model is built again), then ``("frame", timestamp, values)`` per frame,
``("log", text)``, and ``("error", error)`` when the run cannot go on.
"""

from __future__ import annotations

import multiprocessing
import queue
import threading
import time
from datetime import datetime, timedelta, timezone

from .engine import SimEngine
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


class _Latest:
    """The state sent to the controller by a thread of its own, only the latest when it is behind: a
    state replaces the one still waiting, keeping its rejections, so the loop never waits on the link
    and the controller never reads an old state."""

    def __init__(self, link) -> None:
        self._link, self._state = link, None
        self._ready = threading.Condition()
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="rtsim-state", daemon=True)
        self._thread.start()

    def put(self, state: tuple) -> None:
        with self._ready:
            if self._state is not None:
                *rest, rejected = state
                state = (*rest, self._state[-1] + rejected)
            self._state = state
            self._ready.notify()

    def close(self) -> None:
        with self._ready:
            self._closed = True
            self._ready.notify()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        try:
            while True:
                with self._ready:
                    while self._state is None and not self._closed:
                        self._ready.wait()
                    if self._state is None:
                        return
                    state, self._state = self._state, None
                self._link.send(state)
        except (BrokenPipeError, EOFError, OSError):
            return


def _serve(down, link, up, model, dt, rate, steps, measurements, ids) -> None:  # noqa: PLR0913
    """The engine process: ``_run``, with what it sends flushed before the process ends."""
    up = _Outbox(up)
    latest = _Latest(link) if link is not None else None
    try:
        _run(up, down, link, latest, model, dt, rate, steps, measurements, ids)
    finally:
        if latest is not None:
            latest.close()
        up.close()


def _run(up, down, link, latest, model, dt, rate, steps, measurements, ids) -> None:  # noqa: PLR0913
    """Build, then step in real time until told to stop, sending each frame up."""
    try:
        engine = SimEngine(model, dt=dt)
        layout = pmu_layout(measurements, engine, ids, rate)
    except Exception as error:  # noqa: BLE001 -- the caller raises it
        up.send(("error", error))
        return
    up.send(("header", layout.header))
    build, frames, rejected = 0, 0, []

    def apply(message: tuple) -> None:
        nonlocal layout, build
        if message[0] == "build":
            _, number, new_model, new_ids = message
            try:
                engine.rebuild(new_model)
            except Exception as error:  # noqa: BLE001 -- the running simulation goes on as it was
                up.send(("log", f"the model could not be built again: {error}; the simulation goes on as it was"))
                return
            build, layout = number, pmu_layout(measurements, engine, new_ids, rate)
            up.send(("header", layout.header))
            return
        try:
            engine.apply(message)
        except Exception as error:  # noqa: BLE001 -- said back to the controller, and the run goes on
            rejected.append((message[1], f"{type(error).__name__}: {error}"))
            up.send(("log", f"could not apply {message[1]}: {error}"))

    period = 1.0 / rate
    origin, due = datetime.now(timezone.utc), time.monotonic()
    start = due
    try:
        while True:
            while down.poll():
                if down.recv() is None:
                    return
            try:
                while link is not None and link.poll():
                    apply(link.recv())
            except (EOFError, OSError):  # the controller is gone: the simulation goes on as it is
                up.send(("log", "the simulation is no longer steered"))
                link = None
            for message in engine.due():  # what was sent for now: a fault's clearing
                apply(message)
            due += period
            delay = due - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            elif -delay > MAX_LAG:  # far behind: drop the time rather than burst through it
                due = time.monotonic()
            snapshot = engine.step(steps)
            frames += 1
            up.send(("frame", origin + timedelta(seconds=due - start), pmu_values(layout, snapshot)))
            if link is not None:
                latest.put(("state", build, frames, *engine.state(), rejected))
                rejected = []
    except (BrokenPipeError, EOFError, KeyboardInterrupt):
        return
    except Exception as error:  # noqa: BLE001 -- the caller raises it
        up.send(("error", error))


class EngineProcess:
    """The simulation of ``model`` run in real time at ``rate`` frames per second of ``steps`` steps of
    ``dt``, measured as the graph's ``measurements`` say (``ids`` is the export's ``sim.ids``), steered through ``link`` (the
    engine's end of a duplex pipe to the controller, which it takes over). ``receive`` what it sends
    up (blocking: from a thread)."""

    def __init__(
        self,
        model: dict,
        *,
        dt: float,
        rate: float,
        steps: int,
        measurements: list[Measured],
        ids: dict,
        link=None,
    ) -> None:
        context = multiprocessing.get_context("spawn")  # nothing of the server's state comes along
        down_read, self._down = context.Pipe(duplex=False)
        self._up, up_write = context.Pipe(duplex=False)
        self._process = context.Process(
            target=_serve,
            args=(down_read, link, up_write, model, dt, rate, steps, measurements, ids),
            name="rtsim-engine",
            daemon=True,
        )
        self._process.start()
        down_read.close()
        up_write.close()
        if link is not None:
            link.close()  # the engine's process has its own

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
