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
over from (``("build", n, model, ids, events)``, ``LiveTops.built``), applied before the next frame's steps. Up it goes the state after
each frame (``("state", build, frame, t, y, v, rejected)``), only the latest one when the controller
is busy (a refresh takes a second): it reads the simulation from that, and is told which of the
events it sent could not be applied.

Two more pipes, with the server: down, ``None`` to stop; up, the frame layout's ``header`` (first,
and again when the model is built again), then ``("frame", timestamp, values)`` per frame,
``("scan", timestamp, sim_time, analogs, discretes)`` per SCADA scan (``scada``: at the first frame,
then every ``scada_period`` seconds of the simulation's clock; none when it is 0),
``("log", text)``, and ``("error", error)`` when the run cannot go on. A bus left with no admittance
(TOPS's ``DeadBusWarning``: an island's bay with every breaker open) is held at 0 V, and said once.
"""

from __future__ import annotations

import multiprocessing
import queue
import re
import threading
import time
import warnings
from datetime import datetime, timedelta, timezone

from tops.events import DeadBusWarning

from .engine import SimEngine
from .pmu import Measured, pmu_layout, pmu_values
from .scada import scada_layout, scada_values

__all__ = ["EngineProcess", "LAG_WARNING", "LAG_WARNING_EVERY"]

#: Seconds behind its schedule past which the simulation is said to lag (a warning), and how often
#: it is said again while it does.
LAG_WARNING = 1.0
LAG_WARNING_EVERY = 10.0


class _Pacer:
    """When each frame goes, and what it is stamped. Frame ``k`` (from 1) is due ``k / rate`` seconds
    after ``start`` and stamped there: a schedule never reset, so two frames are always ``1 / rate``
    apart, as the simulation's own steps are, and a frame stamped is the simulation's state at that
    time. One that is late goes as soon as it can, but no sooner than ``1 / (rate * catch_up)`` after
    the one before: a lag (a busy machine, a model built again) is made up at ``catch_up`` times real
    time at most, and no time is dropped. One that cannot keep up only falls further behind, said by
    ``report``. Pure: the clock is the caller's."""

    def __init__(self, rate: float, catch_up: float, start: float) -> None:
        self.period, self.gap, self.start = 1.0 / rate, 1.0 / (rate * catch_up), start
        self.catch_up = catch_up
        #: Frames gone, and when the last one went.
        self.frames, self._last = 0, None
        self._warned_at: float | None = None

    def wait(self, now: float) -> float:
        """Seconds to wait before the next frame."""
        due = self.start + (self.frames + 1) * self.period
        earliest = due if self._last is None else max(due, self._last + self.gap)
        return max(0.0, earliest - now)

    def go(self, now: float) -> float:
        """The next frame goes at ``now``: its stamp, in seconds after ``start``."""
        self.frames += 1
        self._last = now
        return self.frames * self.period

    def lag(self, now: float) -> float:
        """Seconds behind the schedule: how late the last frame went (0 when on time)."""
        return max(0.0, now - (self.start + self.frames * self.period))

    def report(self, now: float) -> tuple[str, str] | None:
        """What to say of the lag now, if anything: ``("warning", text)`` past ``LAG_WARNING``, again
        every ``LAG_WARNING_EVERY`` seconds while it lasts; ``("log", text)`` once caught up."""
        lag = self.lag(now)
        if lag > LAG_WARNING:
            if self._warned_at is None or now - self._warned_at >= LAG_WARNING_EVERY:
                self._warned_at = now
                return "warning", (
                    f"the simulation is {lag:.1f} s behind real time: catching up at up to "
                    f"{self.catch_up:g} times real time, nothing dropped"
                )
        elif self._warned_at is not None and lag < self.period:
            self._warned_at = None
            return "log", "the simulation has caught up with real time"
        return None


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


def _say_dead_buses(up) -> None:
    """Have TOPS's ``DeadBusWarning`` said up as a log line, once per bus however often it comes back
    (the engine's process is ours: the hook is global to it); every other warning as before."""
    said: set[str] = set()
    shown = warnings.showwarning

    def show(message, category, *args, **kwargs) -> None:
        if not issubclass(category, DeadBusWarning):
            shown(message, category, *args, **kwargs)
            return
        buses = [bus for bus in re.findall(r"'([^']*)'", str(message)) if bus not in said]
        if buses:
            said.update(buses)
            up.send(("log", f"no admittance left at {', '.join(buses)}: held at 0 V"))

    warnings.simplefilter("always", DeadBusWarning)
    warnings.showwarning = show


def _serve(down, link, up, model, dt, rate, steps, measurements, ids, scada_period=0.0, events=(), catch_up=1.5) -> None:  # noqa: PLR0913
    """The engine process: ``_run``, with what it sends flushed before the process ends."""
    up = _Outbox(up)
    latest = _Latest(link) if link is not None else None
    _say_dead_buses(up)
    try:
        _run(up, down, link, latest, model, dt, rate, steps, measurements, ids, scada_period, events, catch_up)
    finally:
        if latest is not None:
            latest.close()
        up.close()


def _run(up, down, link, latest, model, dt, rate, steps, measurements, ids, scada_period=0.0, events=(), catch_up=1.5) -> None:  # noqa: PLR0913
    """Build, then step in real time until told to stop, sending each frame up."""
    try:
        engine = SimEngine(model, dt=dt, events=events)
        layout = pmu_layout(measurements, engine, ids, rate)
        scada = scada_layout(measurements, engine, ids) if scada_period > 0 else None
    except Exception as error:  # noqa: BLE001 -- the caller raises it
        up.send(("error", error))
        return
    up.send(("header", layout.header))
    build, frames, rejected = 0, 0, []
    next_scan = 0.0  # on the simulation's clock: the first frame is scanned

    def apply(message: tuple) -> None:
        nonlocal layout, scada, build
        if message[0] == "build":
            _, number, new_model, new_ids, events = message
            try:
                engine.rebuild(new_model, events)
            except Exception as error:  # noqa: BLE001 -- the running simulation goes on as it was
                up.send(("log", f"the model could not be built again: {error}; the simulation goes on as it was"))
                return
            build, layout = number, pmu_layout(measurements, engine, new_ids, rate)
            scada = scada_layout(measurements, engine, new_ids) if scada_period > 0 else None
            up.send(("header", layout.header))
            return
        try:
            engine.apply(message)
        except Exception as error:  # noqa: BLE001 -- said back to the controller, and the run goes on
            rejected.append((message[1], f"{type(error).__name__}: {error}"))
            up.send(("log", f"could not apply {message[1]}: {error}"))

    origin = datetime.now(timezone.utc)
    pacer = _Pacer(rate, catch_up, time.monotonic())
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
            delay = pacer.wait(time.monotonic())
            if delay > 0:
                time.sleep(delay)
            now = time.monotonic()
            stamped = origin + timedelta(seconds=pacer.go(now))  # its place in the schedule, never the clock
            if said := pacer.report(now):
                up.send(said)
            snapshot = engine.step(steps)
            frames += 1
            up.send(("frame", stamped, pmu_values(layout, snapshot)))
            if scada is not None and snapshot.sim_time_s >= next_scan - 1e-9:
                up.send(("scan", stamped, snapshot.sim_time_s, *scada_values(scada, engine.flows())))
                next_scan = max(next_scan + scada_period, snapshot.sim_time_s + 0.5 * scada_period)
            if link is not None:
                latest.put(("state", build, frames, *engine.state(), rejected))
                rejected = []
    except (BrokenPipeError, EOFError, KeyboardInterrupt):
        return
    except Exception as error:  # noqa: BLE001 -- the caller raises it
        up.send(("error", error))


class EngineProcess:
    """The simulation of ``model`` (``events`` applied right after its initialisation: ``LiveTops.built``)
    run in real time at ``rate`` frames per second of ``steps`` steps of ``dt``, measured as the graph's ``measurements`` say (``ids`` is the export's ``sim.ids``), steered through ``link`` (the
    engine's end of a duplex pipe to the controller, which it takes over), scanning the graph's SCADA
    measurements every ``scada_period`` seconds of the simulation's clock (0: never). ``receive`` what it
    sends up (blocking: from a thread)."""

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
        scada_period: float = 0.0,
        events: list[tuple] = (),
        catch_up: float = 1.5,
    ) -> None:
        context = multiprocessing.get_context("spawn")  # nothing of the server's state comes along
        down_read, self._down = context.Pipe(duplex=False)
        self._up, up_write = context.Pipe(duplex=False)
        self._process = context.Process(
            target=_serve,
            args=(down_read, link, up_write, model, dt, rate, steps, measurements, ids, scada_period, list(events), catch_up),
            name="rtsim-engine",
            daemon=True,
        )
        self._process.start()
        down_read.close()
        up_write.close()
        if link is not None:
            link.close()  # the engine's process has its own

    def receive(self, timeout: float | None = None) -> list[tuple]:
        """What was sent up since the last call, at least one message (blocking: from a thread): each
        ``("header", h)``, ``("frame", t, values)``, ``("scan", t, sim_time, analogs, discretes)``,
        ``("log", text)`` or ``("error", e)``, and
        ``("error", RuntimeError)`` when the process is gone. All at once, so that a busy server pays
        for one wake-up however many frames came meanwhile. With a ``timeout``, nothing (``[]``) when
        nothing came within it."""
        try:
            if timeout is not None and not self._up.poll(timeout):
                return []
            messages = self._up.recv()
            while self._up.poll():
                messages += self._up.recv()
            return messages
        except (EOFError, OSError):
            return [("error", RuntimeError("the simulation process ended"))]

    def close(self, timeout: float = 5.0) -> None:
        """Stop the process: told to, then ended if it has not within ``timeout`` seconds. One still
        building reads nothing until it runs, so a caller that needs nothing from it passes 0."""
        try:
            self._down.send(None)
        except (BrokenPipeError, OSError):
            pass
        self._process.join(timeout=timeout)
        if self._process.is_alive():
            self._process.terminate()
        self._down.close()
        self._up.close()
