# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The RT sim (CIM) source: a live TOPS simulation of the grid in the CIM graph.

It reads the graph (``pswamp_core.cim``) through a repository of its own, exports it with LazyCIM
as a TOPS dynamic model (``engine``), and runs it **in real time**: one frame period of simulated
time per frame period of the clock. It publishes ``PmuFrame``: one column group per PMU Analog of
the graph, each column carrying its Analog (``pmu``), ``RATE`` frames per second.

It has no commands. **The graph is how it is steered**: whoever edits the graph (the CIM graph app,
its one writer) steers the simulation. A follower brings the export up to date with LazyCIM's
``refresh`` (``follow``) when the graph's version stamp says it changed: it looks at the stamp every
``POLL`` seconds (one tiny query), and only then reads the profiles that change (SSH, SV); what
changed is applied before the next frame's steps. A change reaches the simulation within about
``POLL`` and one refresh. Over a shared store (Oxigraph) the follower is **a process of its own**
(``follow.FollowerProcess``), which sends what changed straight to the engine's: a refresh is a
second or so of Python, which in the server's process held up the frames on their way to the pages
(about 2.5 s without a frame, at each edit). Over an in-process store it is a thread here.

**Pacing** is the engine's own: the model is built, stepped and paced in **a process of its own**
(``process.EngineProcess``), which keeps one frame period of steps per frame period of a monotonic
clock, stamps each frame with its place in that schedule, and sends its values up. A frame that comes
late (on Windows a sleep may last 15 ms more than asked) is made up by the next ones; only when it is
more than ``MAX_LAG`` behind is the lost time dropped. In the server's process, a step's many small
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
import time
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from pswamp_core.cim import CimSettings, GraphVersion, Store, connect_reader, open_store
from pswamp_core.log import get_logger
from pswamp_core.settings import EnvSetting
from pswamp_core.sources import SourceModule
from pswamp_core.util.time import utcnow
from pswamp_models.pmu import PmuFrame

from .follow import Follower, FollowerProcess
from .pmu import read_analogs
from .process import MAX_LAG, EngineProcess

__all__ = ["MAX_LAG", "RtsimFromCimSource", "follows_apart"]

logger = get_logger("pswamp_modules.rtsim_from_cim")

#: What the frames say they are about.
STREAM_ID = "rtsim-from-cim"


class RtsimFromCimSource(SourceModule):
    name = "rtsim-from-cim"
    kind = "live"
    cim = True
    outputs = (PmuFrame,)
    env_settings = (
        EnvSetting("RATE", "Frames per second", default="50", kind="float"),
        EnvSetting("DT", "Integration step, simulated seconds", default="0.01", kind="float"),
        EnvSetting("POLL", "Seconds between two looks at the graph's version stamp", default="0.2", kind="float"),
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
        self._graph = graph
        self._repo = repo

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
        follower: Follower | FollowerProcess | None = None
        watch: asyncio.Task | None = None
        engine: EngineProcess | None = None

        try:
            # Starting takes seconds (the graph is read and exported, the load flow solved), and a
            # window may close before it is done: then the stream ends, and the start is left to finish.
            if apart:
                follower = FollowerProcess(settings, poll=self.settings.poll)
                starting = loop.run_in_executor(graph, follower.ready)
            else:
                starting = loop.run_in_executor(graph, self._start)
            if end is not None:
                await asyncio.wait({starting}, timeout=max(0.0, (end - utcnow()).total_seconds()))
                if not starting.done():
                    return
            model, open_switches, ids, analogs = await starting
            if not apart:
                follower = self._follower
            engine = EngineProcess(
                model,
                open_switches=open_switches,
                dt=self.settings.dt,
                rate=self.settings.rate,
                steps=self.steps_per_frame,
                analogs=analogs,
                ids=ids,
                changes=follower.changes if apart else None,
            )
            watch = asyncio.create_task(self._relay(follower, graph) if apart else self._follow(follower, engine, graph))
            header = None
            meter = RateMeter(self.settings.rate)
            while True:
                for kind, *message in await loop.run_in_executor(receive, engine.receive):
                    if kind == "error":
                        raise message[0]
                    if kind == "log":
                        logger.info("%s", message[0])
                    elif kind == "header":
                        header = message[0]
                    else:
                        stamped, values = message
                        if end is not None and stamped >= end:
                            return
                        meter.tick()
                        yield PmuFrame(timestamp=stamped, mRID=STREAM_ID, header=header, values=values)
        finally:
            if watch is not None:
                watch.cancel()
            if engine is not None:
                await loop.run_in_executor(None, engine.close)
            if isinstance(follower, FollowerProcess):
                await loop.run_in_executor(None, follower.close)
            receive.shutdown(wait=True, cancel_futures=True)
            graph.shutdown(wait=False, cancel_futures=True)  # a start still running finishes on its own

    def _start(self) -> tuple:
        """Connect, export the graph and read its PMU Analogs (in the graph's thread)."""
        store = Store.of(self._repo) if self._repo is not None else open_store(self._graph)
        version = GraphVersion(store)  # watched from before the export
        repo = self._connect()
        self._follower = Follower(repo, version)
        sim = self._follower.sim
        return sim.model, self._follower.open_switches, sim.ids, read_analogs(repo)

    async def _follow(self, follower: Follower, engine: EngineProcess, graph: ThreadPoolExecutor) -> None:
        """The graph followed from a thread of the server's process (a store of its own)."""
        loop = asyncio.get_running_loop()
        while True:
            started = time.monotonic()
            try:
                change = await loop.run_in_executor(graph, follower.changes)
                if change:
                    await loop.run_in_executor(graph, engine.send, change)
            except Exception as error:  # a store that is down for a moment must not end the stream
                logger.warning("the graph could not be read, the simulation keeps its last state: %s", error)
            took = time.monotonic() - started
            # At most every POLL, and busy a quarter of the time at most: a refresh is Python work in
            # the server's process, which everything else there shares.
            await asyncio.sleep(max(self.settings.poll - took, 3 * took))

    @staticmethod
    async def _relay(follower: FollowerProcess, graph: ThreadPoolExecutor) -> None:
        """What the follower's process says, logged here (from the graph's thread, free once it has
        started: its wait ends when the follower does)."""
        loop = asyncio.get_running_loop()
        while (said := await loop.run_in_executor(graph, follower.receive)) is not None:
            logger.warning("%s", said)


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
