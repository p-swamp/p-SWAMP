# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The RT sim (CIM) source: a live TOPS simulation of the grid in the CIM graph.

It reads the graph (``pswamp_core.cim``) through a repository of its own, simulates it with
LazyCIM's ``LiveTops`` (TOPS 0.6), and runs the simulation **in real time**: one frame period of
simulated time per frame period of the clock. It publishes ``PmuFrame``: one column per PMU
measurement of the graph, each column carrying its own Analog (``pmu``), ``RATE`` frames per second;
and, every ``SCADA_PERIOD`` seconds of the simulation's clock, a ``ScadaScan``: the value of every SCADA
measurement of the graph (``scada``), which the graph's one writer keeps as the latest (ADR-016).

**It takes commands** (ADR-015, ``follow.COMMANDS``): an operation (a switch, the terminal of a line
that has no breaker) or a disturbance (a branch tripped or reconnected, a short circuit, a load
step), or a reset. Each is announced as a ``SimEvent``; an operation, once the engine has applied
it, is also said as ``CimEdits`` for the graph's one writer; a disturbance never is. **It also
follows the graph**: whoever edits it (the CIM graph app, its one writer) steers the simulation too.
A controller (``follow``) holds ``LiveTops``, which
follows the graph when its version stamp says it changed: it looks at the stamp every ``POLL``
seconds (one tiny query), and only then reads the profiles that change (SSH, SV). ``LiveTops``
decides what a change means for the running simulation, and the controller sends it to the engine's
process (``runner``), where it is applied before the next frame's steps. A change reaches the
simulation within about ``POLL`` and one refresh. Over a shared store (Oxigraph) the controller is
**a process of its own** (``follow.ControllerProcess``), linked straight to the engine's: a refresh is
a second or so of Python, which in the server's process held up the frames on their way to the pages
(about 2.5 s without a frame, at each edit). Over an in-process store it is a thread here.

**Pacing** is the engine's own: the model is built, stepped and paced in **a process of its own**
(``process.EngineProcess``), which keeps one frame period of steps per frame period of a monotonic
clock, stamps each frame with its place in that schedule, and sends its values up. The schedule is
never reset and no time is dropped: a frame that comes late (on Windows a sleep may last 15 ms more
than asked; a busy machine, a model built again) is made up by the next ones, at up to ``CATCH_UP``
times real time, so two frames are always one period apart, and a lag past a second is a warning. In
the server's process, a step's many small
numpy calls (and the pacing) would each wait their turn for the interpreter behind every other thread
(four steps of Nordic44 took 4 ms alone and 834 ms next to one busy thread); here the server only
turns each frame's values into a ``PmuFrame``, and a busy server delays a few frames but loses none.
A grid that cannot be read or
simulated, or a run that diverges, ends the stream with the error; reading the source again starts a
fresh simulation at t = 0 from the graph as it is then.

From a script there is no server: the graph is the process's own (the sample grid, with
``PSWAMP_CIM_PATH``), and a bounded window is read (``examples/run_rtsim.py``). A script that holds
a grid in any LazyCIM store hands its repository over instead (``repo=``): the source then reads
that, follows it from a thread, and, the store having no version stamp, looks for edits every
couple of seconds (``pswamp_core.cim.GraphVersion``).
"""

from __future__ import annotations

import asyncio
import multiprocessing
import time
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from pswamp_core.cim import CimSettings, GraphVersion, Store, connect_reader, model_id, open_store
from pswamp_core.command_routing import CommandRefused
from pswamp_core.log import get_logger
from pswamp_core.settings import EnvSetting
from pswamp_core.sources import SourceModule
from pswamp_core.util.time import utcnow
from pswamp_models.cim import CimEdits
from pswamp_models.common import Command, DataModel
from pswamp_models.pmu import PmuFrame
from pswamp_models.rtsim import (
    ClearShortCircuitCommand,
    FaultAndClearCommand,
    LoadStepCommand,
    OperateLineCommand,
    OperateSwitchCommand,
    ReconnectBranchCommand,
    ShortCircuitCommand,
    SimEvent,
    TripBranchCommand,
)
from pswamp_models.scada import AnalogReading, DiscreteReading, ScadaScan

from .follow import COMMANDS, Controller, ControllerProcess
from .pmu import read_measurements
from .process import EngineProcess
from .protection import ProtectionSettings

__all__ = ["RtsimFromCimSource", "follows_apart"]

logger = get_logger("pswamp_modules.rtsim_from_cim")

#: What the frames say they are about.
STREAM_ID = "rtsim-from-cim"


class RtsimFromCimSource(SourceModule):
    name = "rtsim-from-cim"
    kind = "live"
    cim = True
    outputs = (PmuFrame, CimEdits, SimEvent, ScadaScan)
    commands = COMMANDS
    env_settings = (
        EnvSetting("RATE", "Frames per second", default="50", kind="float"),
        EnvSetting("DT", "Integration step, simulated seconds", default="0.01", kind="float"),
        EnvSetting("POLL", "Seconds between two looks at the graph's version stamp", default="0.2", kind="float"),
        EnvSetting("PROTECTION", "Whether a line over its current limit is tripped: on or off", default="on"),
        EnvSetting("OVERLOAD_PICKUP", "The multiple of a line's permanent limit it trips over", default="1.0", kind="float"),
        EnvSetting("OVERLOAD_TMS", "The overload curve's time multiplier (IEC standard inverse)", default="0.5", kind="float"),
        EnvSetting("SCADA_PERIOD", "Seconds of simulated time between two SCADA scans; 0: none", default="2", kind="float"),
        EnvSetting("CATCH_UP", "How many times real time a simulation behind its schedule runs to catch up", default="1.5", kind="float"),
    )

    def __init__(
        self, source: str | None = None, *, graph: CimSettings | None = None, repo=None, **settings
    ) -> None:
        """``graph`` says where the CIM graph is (the environment's when omitted); ``repo``, a script's
        own LazyCIM repository over any store, is read instead. The source then owns it: the script
        edits the grid through a second repository over the same store, never through this one."""
        super().__init__(source, **settings)
        rate, dt = self.settings.rate, self.settings.dt
        if rate <= 0 or dt <= 0 or self.settings.poll <= 0:
            raise ValueError(f"RATE ({rate}), DT ({dt}) and POLL ({self.settings.poll}) must be positive")
        #: Integration steps per frame period.
        self.steps_per_frame = round(1.0 / (rate * dt))
        if self.steps_per_frame < 1 or abs(self.steps_per_frame * rate * dt - 1.0) > 1e-6:
            raise ValueError(f"RATE ({rate}) and DT ({dt}) must make a whole number of steps per frame period")
        if self.settings.protection not in ("on", "off"):
            raise ValueError(f"PROTECTION is on or off, not {self.settings.protection!r}")
        if self.settings.overload_pickup <= 0 or self.settings.overload_tms <= 0:
            raise ValueError("OVERLOAD_PICKUP and OVERLOAD_TMS must be positive")
        if self.settings.scada_period < 0:
            raise ValueError(f"SCADA_PERIOD ({self.settings.scada_period}) is 0 (no scans) or positive")
        if self.settings.catch_up < 1:
            raise ValueError(f"CATCH_UP ({self.settings.catch_up}) is 1 (never faster than real time) or more")
        self.protection = ProtectionSettings(
            enabled=self.settings.protection == "on",
            pickup=self.settings.overload_pickup,
            tms=self.settings.overload_tms,
        )
        self._graph = graph
        self._repo = repo
        #: The running simulation, as commands reach it; ``None`` while it does not run.
        self._steering: _Steering | None = None

    # -- commands -----------------------------------------------------------------------------

    def validate(self, command: Command) -> None:
        """Refuse a command while the simulation does not run, or for an object it does not have."""
        steering = self._steering
        if steering is None:
            raise CommandRefused(f"{command.name}: the simulation is not running")
        _check(command, steering.ids())

    async def ahandle(self, command: Command) -> list[DataModel]:
        """Hand ``command`` to the controller; what it announces (a ``SimEvent``) is the answer, and what
        it reports later (``CimEdits``) comes with the frames."""
        steering = self._steering
        if steering is None:
            raise CommandRefused(f"{command.name}: the simulation is not running")
        return await steering.command(command)

    def _connect(self):
        if self._repo is not None:
            self.cim_repo = self._repo
        elif self._graph is not None and self._cim_repo is None:
            self.cim_repo = connect_reader(self._graph)
        return self.cim_repo

    async def aread(self, start: datetime | None = None, end: datetime | None = None) -> AsyncIterator[PmuFrame]:
        receive = ThreadPoolExecutor(1, thread_name_prefix="rtsim")
        graph = ThreadPoolExecutor(1, thread_name_prefix="rtsim-graph")  # owns the repository
        loop = asyncio.get_running_loop()
        settings = self._graph or CimSettings.from_env()
        apart = self._repo is None and follows_apart(settings)  # a repository cannot leave the process
        controller: Controller | ControllerProcess | None = None
        watch: asyncio.Task | None = None
        engine: EngineProcess | None = None
        ours = theirs = None
        header = None

        try:
            # Starting takes seconds (the graph is read and exported, the load flow solved), and a
            # window may close before it is done: then the stream ends, and the start is left to finish.
            if apart:
                controller = ControllerProcess(settings, poll=self.settings.poll, dt=self.settings.dt, protection=self.protection)
                starting = loop.run_in_executor(graph, controller.ready)
            else:
                ours, theirs = multiprocessing.get_context("spawn").Pipe()  # the controller's end, the engine's
                starting = loop.run_in_executor(graph, self._start, ours)
            if end is not None:
                await asyncio.wait({starting}, timeout=max(0.0, (end - utcnow()).total_seconds()))
                if not starting.done():
                    return
            model, ids, measurements, events = await starting
            # The engine stamps its frames from when it is built: none can fall in a window closed by now.
            if end is not None and utcnow() >= end:
                return
            if not apart:
                controller = self._controller
            reference = await loop.run_in_executor(graph, self._reference, settings)
            engine = EngineProcess(
                model,
                dt=self.settings.dt,
                rate=self.settings.rate,
                steps=self.steps_per_frame,
                measurements=measurements,
                ids=ids,
                link=controller.link if apart else theirs,
                scada_period=self.settings.scada_period,
                events=events,
                catch_up=self.settings.catch_up,
            )
            theirs = None  # the engine's process took it over
            steering = self._steering = _Steering(controller, graph, ids)
            watch = asyncio.create_task(self._relay(steering) if apart else self._follow(steering, ours))
            meter = RateMeter(self.settings.rate)
            while True:
                # Until its header, the engine is building; it stamps from after that, so a window that
                # closes meanwhile gets nothing from it, and the stream ends rather than wait.
                building = end is not None and header is None
                timeout = max(0.0, (end - utcnow()).total_seconds()) if building else None
                received = await loop.run_in_executor(receive, engine.receive, timeout)
                if building and not received:
                    return
                while not steering.said.empty():
                    yield steering.said.get_nowait()
                for kind, *message in received:
                    if kind == "error":
                        raise message[0]
                    if kind == "log":
                        logger.info("%s", message[0])
                    elif kind == "warning":
                        logger.warning("%s", message[0])
                    elif kind == "header":
                        header = message[0]
                    elif kind == "scan":
                        stamped, sim_time, analogs, discretes = message
                        if end is not None and stamped >= end:
                            return
                        yield ScadaScan(
                            timestamp=stamped,
                            source=STREAM_ID,
                            sim_time=sim_time,
                            cimReferenceId=reference,
                            analogs=[AnalogReading(mRID=mrid, value=value) for mrid, value in analogs],
                            discretes=[DiscreteReading(mRID=mrid, value=value) for mrid, value in discretes],
                        )
                    else:
                        stamped, values = message
                        if end is not None and stamped >= end:
                            return
                        meter.tick()
                        yield PmuFrame(timestamp=stamped, mRID=STREAM_ID, header=header, values=values)
        finally:
            self._steering = None
            if watch is not None:
                watch.cancel()
            if engine is not None:  # one still building is not waited for: it would not read the stop
                await loop.run_in_executor(None, engine.close, 5.0 if header is not None else 0.0)
            if isinstance(controller, ControllerProcess):
                await loop.run_in_executor(None, controller.close)
            for end_ in (ours, theirs):
                if end_ is not None:
                    end_.close()
            receive.shutdown(wait=True, cancel_futures=True)
            graph.shutdown(wait=False, cancel_futures=True)  # a start still running finishes on its own

    def _reference(self, settings: CimSettings) -> str | None:
        """The grid's model id, what a scan says it is of (in the graph's thread)."""
        try:
            return model_id(Store.of(self._repo) if self._repo is not None else open_store(settings))
        except Exception as error:  # a store that does not say: the scans say nothing either
            logger.warning("the grid's model id cannot be read: %s", error)
            return None

    def _start(self, link) -> tuple:
        """Connect, simulate the graph with ``LiveTops`` steering the engine at the other end of ``link``,
        and read its measurements (in the graph's thread)."""
        store = Store.of(self._repo) if self._repo is not None else open_store(self._graph)
        version = GraphVersion(store)  # watched from before the export
        repo = self._connect()
        self._controller = Controller(repo, version, dt=self.settings.dt, protection=self.protection)
        self._controller.attach(link.send)
        built = self._controller.live.built  # the model less what is left out, and what to apply after
        return built.model, self._controller.sim.ids, read_measurements(repo), built.events

    async def _follow(self, steering: _Steering, link) -> None:
        """The graph followed, and the simulation's reports taken, from a thread of the server's process
        (a store of its own). Two paces: what the engine sends and what the simulation reports are
        taken every ``POLL``, which is cheap; the graph is followed at most every ``POLL`` and busy a
        quarter of the time at most, since a refresh is Python work in the server's process, which
        everything else there shares. A report so never waits for the graph's back-off."""
        loop, controller = asyncio.get_running_loop(), steering.controller

        def take() -> list[CimEdits] | None:
            try:
                while link.poll():
                    controller.receive(link.recv())
            except (EOFError, OSError):
                return None  # the engine is gone, and the stream with it
            return controller.reports()

        due = 0.0  # when the graph is next followed
        while True:
            started = time.monotonic()
            try:
                reports = await loop.run_in_executor(steering.graph, take)
                if reports is None:
                    return
                for report in reports:
                    steering.said.put_nowait(report)
                if started >= due:
                    try:
                        for line in await loop.run_in_executor(steering.graph, controller.changes):
                            logger.info("%s", line)
                    finally:
                        took = time.monotonic() - started
                        due = time.monotonic() + max(self.settings.poll - took, 3 * took)
            except Exception as error:  # a store that is down for a moment must not end the stream
                logger.warning("the graph could not be followed, the simulation keeps its last state: %s", error)
            await asyncio.sleep(max(0.0, self.settings.poll - (time.monotonic() - started)))

    @staticmethod
    async def _relay(steering: _Steering) -> None:
        """What the controller's process says, taken here (from the graph's thread, free once it has
        started: its wait ends when the controller does): its logs, its reports, its answers to
        commands, and the ids of a model built again."""
        loop, controller = asyncio.get_running_loop(), steering.controller
        while (said := await loop.run_in_executor(steering.graph, controller.receive)) is not None:
            kind, *rest = said
            if kind in ("log", "warning"):
                (logger.info if kind == "log" else logger.warning)("%s", rest[0])
            elif kind == "said":
                for report in rest[0]:
                    steering.said.put_nowait(report)
            elif kind == "answer":
                steering.answered(*rest)
            elif kind == "ids":
                steering.known = rest[0]


class _Steering:
    """The running simulation, as commands reach it: its controller (a thread's ``Controller``, or a
    ``ControllerProcess``), the ids of its model, and what it says beside the frames."""

    #: How long a command may wait for the controller (one busy refreshing the export, say).
    ANSWER_S = 30.0

    def __init__(self, controller: Controller | ControllerProcess, graph: ThreadPoolExecutor, ids: dict) -> None:
        self.controller, self.graph, self.known = controller, graph, ids
        self.said: asyncio.Queue[DataModel] = asyncio.Queue()
        self._answers: dict[str, asyncio.Future] = {}

    def ids(self) -> dict:
        """The ids of the model running now: the controller's own, or the last a process sent."""
        return self.controller.sim.ids if isinstance(self.controller, Controller) else self.known

    async def command(self, command: Command) -> list[DataModel]:
        loop = asyncio.get_running_loop()
        if isinstance(self.controller, Controller):
            return await loop.run_in_executor(self.graph, self.controller.command, command)
        answer = self._answers[command.request_id] = loop.create_future()
        try:
            self.controller.command(command)
            async with asyncio.timeout(self.ANSWER_S):
                return await answer
        finally:
            self._answers.pop(command.request_id, None)

    def answered(self, request: str, messages: list[DataModel] | None, refused: str | None) -> None:
        answer = self._answers.get(request)
        if answer is not None and not answer.done():
            if refused is not None:
                answer.set_exception(CommandRefused(refused))
            else:
                answer.set_result(messages)


#: What each command acts on, as the model's ids name it: a component of ``ids`` whose values are
#: mRIDs, or ``node_to_bus``, whose keys are.
_OBJECTS = {
    OperateSwitchCommand: (("switches",), "switch"),
    OperateLineCommand: (("lines", "transformers"), "line or transformer"),
    TripBranchCommand: (("lines", "transformers"), "line or transformer"),
    ReconnectBranchCommand: (("lines", "transformers"), "line or transformer"),
    ShortCircuitCommand: (("node_to_bus",), "node"),
    ClearShortCircuitCommand: (("node_to_bus",), "node"),
    LoadStepCommand: (("loads",), "load"),
    FaultAndClearCommand: (("lines",), "line"),
}


def _check(command: Command, ids: dict) -> None:
    """Refuse a command for an object the running model does not have."""
    found = _OBJECTS.get(type(command))
    if found is None:
        return
    components, kind = found
    mrid = command.mRID
    for component in components:
        group = ids.get(component, {})
        if mrid in (group if component == "node_to_bus" else group.values()):
            return
    raise CommandRefused(f"{mrid} is no {kind} of the simulation")


def follows_apart(settings: CimSettings) -> bool:
    """Whether the graph is followed from a process of its own: when the store is shared (Oxigraph, or
    a ``backend`` marked ``shared``), which another process can read. An in-process store (tests,
    scripts) is followed from a thread."""
    if settings.backend is not None:
        return settings.shared
    return settings.url is not None


class RateMeter:
    """Counts the frames a stream yields, and says every ``every`` seconds how many per second it
    managed: at INFO, or at WARNING below 90 % of ``rate``, since a frame that runs late costs the
    stream a frame and says nothing else."""

    def __init__(self, rate: float, every: float = 10.0) -> None:
        self.rate, self.every = rate, every
        #: Counted from the first frame: a model takes seconds to build, which is no frame late.
        self.count, self.since = 0, None
        #: The rate over the last full interval; ``None`` before the first.
        self.last: float | None = None

    def tick(self) -> None:
        if self.since is None:
            self.since = time.monotonic()
            return
        self.count += 1
        elapsed = time.monotonic() - self.since
        if elapsed < self.every:
            return
        self.last = self.count / elapsed
        log = logger.warning if self.last < 0.9 * self.rate else logger.info
        log("%.1f frames/s over the last %.0f s (the rate is %g)", self.last, elapsed, self.rate)
        self.count, self.since = 0, time.monotonic()
