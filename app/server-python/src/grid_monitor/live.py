"""The live grid, as the grid monitor's panels see it: one follower of the grid-monitor pipeline's
shared run, for the whole process.

**There is one grid and one simulation of it** (``pipelines/grid-monitor.toml``), so there is one of
everything here, and every client sees the same: the measurement window, the islands, the alarm list,
the outage log and the modules' statuses. The pipeline is served by the islanding detection app,
whose lifespan starts the shared run; this only reads that run off the transport, as a module would
(and as ``cim_live`` does): its frames on one subscription, which may drop the oldest when the loop is
busy, and its results on another, which drops nothing.

Everything runs on the event loop. A panel reads the state here directly, on its own ticker
(``serve_ticks``), or wakes on what it listens for (``updates``, then ``serve_updates``). An operator
action on an alarm wakes every view with ``nudge``: an alarm is everyone's.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from fastapi import WebSocket
from shared import app_pipeline, get_logger, read_client_id, refuse_socket, transport

from pswamp_core.pipeline import live_key
from pswamp_core.subscription import Overflow
from pswamp_models.common import AlarmEvent as AlarmMessage
from pswamp_models.islanding_detection import IslandingDetectionResult
from pswamp_models.line_outage import LineOutageResult, MeasuredCurrent
from pswamp_models.player import PlayerStatus
from pswamp_models.pmu import PmuFrame
from pswamp_web.pump import Event, offer
from pswamp_web.stores import STALE_AFTER, AlarmStore
from pswamp_web.wire import (
    AppStatus,
    FeedStatus,
    Island,
    IslandingParameters,
    IslandingResult,
    LineOutageEvent,
    LineOutageLog,
    sample,
)

from .topology import Topology, read_topology
from .window import MeasurementWindow

logger = get_logger("grid-monitor")

#: The live grid's pipeline, read here only for where its run is: it is served by the islanding app.
PIPELINE = app_pipeline("grid-monitor")
_LIVE = PIPELINE.live_sources()
if len(_LIVE) != 1:
    raise RuntimeError(f"{PIPELINE.app} must have exactly one live source, the grid's simulation; it has {_LIVE}")
SOURCE = _LIVE[0]
KEY = live_key(SOURCE)

#: Seconds of every column the window keeps: what the measurement panels plot.
WINDOW_SECONDS = 30
#: Frames the follower may fall behind by before the oldest are dropped: 10 s at 50 Hz.
FRAME_BACKLOG = 500
#: A feed that has sent nothing for this long is not streaming.
STREAMING_WITHIN = 2.0
#: Events the outage log keeps.
OUTAGE_LOG = 100

# What wakes a view.
ISLANDING, ALARMS, LINE_OUTAGE = "islanding", "alarms", "line_outage"


@dataclass
class _Status:
    app_name: str
    status: str
    t: float
    received_at: float


class LiveGrid:
    def __init__(self) -> None:
        self._views: list[tuple[asyncio.Queue, frozenset[str]]] = []
        self._topology: asyncio.Future | None = None
        self._cim = ThreadPoolExecutor(1, thread_name_prefix="grid-monitor-cim")
        self.reset()

    def reset(self) -> None:
        """Forget everything heard: the state of a server that has just started."""
        self.window = MeasurementWindow(WINDOW_SECONDS)
        self.alarms = AlarmStore()
        #: The latest islanding assessment, its main system recovered; ``None`` until the first.
        self.islanding: IslandingResult | None = None
        #: Each station's island (0 is the main system), from that assessment.
        self.island_of: dict[str, int] = {}
        self.outages = LineOutageLog(events=[])
        self.topology: Topology | None = None
        self.feed: PlayerStatus | None = None
        self.frames = 0
        self._last_frame_at: float | None = None
        #: One row per module, by name: a run that starts over gets new instances, which replace the old.
        self._statuses: dict[str, tuple[str, _Status]] = {}
        #: Each module's current instance (its app uuid), by name.
        self._instances: dict[str, str] = {}
        self._header = asyncio.Event()

    # --- following the run --------------------------------------------------

    async def follow(self) -> None:
        """Read the shared run until cancelled."""
        link = transport()
        with (
            link.subscribe(PmuFrame, app=PIPELINE.app, key=KEY, overflow=Overflow.DROP_OLDEST, maxsize=FRAME_BACKLOG) as frames,
            link.subscribe(
                PlayerStatus, *PIPELINE.results, app=PIPELINE.app, key=KEY, overflow=Overflow.GROW
            ) as results,
        ):
            await asyncio.gather(self._frames(frames), self._results(results))

    async def _frames(self, frames) -> None:
        async for _, frame in frames:
            self.window.append(frame)
            self.frames += 1
            self._last_frame_at = time.time()
            self._header.set()

    async def _results(self, results) -> None:
        async for _, message in results:
            try:
                self.handle(message)
            except Exception:  # one bad message must not end the follower
                logger.exception("could not handle %s", type(message).__name__)

    def handle(self, message) -> None:
        if isinstance(message, (IslandingDetectionResult, AlarmMessage, LineOutageResult)):
            self._instance(message.app.name, message.app.uuid, message.timestamp.timestamp())
        if isinstance(message, PlayerStatus):
            self.feed = message
        elif isinstance(message, IslandingDetectionResult):
            self._status(message, message.result.status)
            assessment = self._islanding(message)
            if assessment is not None:  # else it was made on another layout: keep the last one
                self.islanding = assessment
                self._wake(ISLANDING)
        elif isinstance(message, AlarmMessage):
            self.alarms.handle(
                {
                    "uuid": message.alarm_uuid,
                    "type": message.type,
                    "time_stamp": message.timestamp,
                    "app": message.app.uuid,
                    "app_name": message.app.name,
                    "message": message.message,
                }
            )
            self._wake(ALARMS)
        elif isinstance(message, LineOutageResult):
            self._status(message, message.result.status)
            if self._outages(message):
                self._wake(LINE_OUTAGE)

    def _instance(self, name: str, uuid: str, t: float) -> None:
        """A module heard from a new instance (its run started over): the old one will never clear
        the alarms it left open, so they are cleared here, or they would stay active for everyone."""
        old = self._instances.get(name)
        self._instances[name] = uuid
        if old is not None and old != uuid and self.alarms.retire(old, t, "Alarm cleared: the module was restarted."):
            self._wake(ALARMS)

    def _status(self, result, status: str) -> None:
        self._statuses[result.app.name] = (result.app.uuid, _Status(result.app.name, status, result.timestamp.timestamp(), time.time()))

    def _islanding(self, result: IslandingDetectionResult) -> IslandingResult | None:
        """The assessment as the panels want it: every group, the main system first, each with its
        mean frequency over the module's window. The module lists the islands and the stations in no
        group; the main system is the rest of the frequency stations of the layout it assessed.
        ``None`` when that is not the window's layout (the simulation has just rebuilt its model)."""
        body, parameters = result.result, result.parameters
        header = self.window.header
        main = body.main_stations(header) if header is not None else None
        if main is None:
            return None
        groups = [(main, body.main_mean_freq), *((island.stations, island.mean_freq) for island in body.islands)]
        self.island_of = {station: index for index, (stations, _) in enumerate(groups) for station in stations}
        return IslandingResult(
            t=result.timestamp.timestamp(),
            app_uuid=result.app.uuid,
            app_name=result.app.name,
            status=body.status,
            islands=[
                Island(index=index, stations=stations, mean_freq=sample(mean_freq))
                for index, (stations, mean_freq) in enumerate(groups)
            ],
            parameters=IslandingParameters(
                window_length=float(parameters.get("window_length_s", 10.0)),
                mean_threshold=float(parameters.get("mean_threshold", 0.0)),
                eval_freq=float(parameters.get("eval_freq", 0.0)),
            ),
        )

    def _outages(self, result: LineOutageResult) -> bool:
        """Fold one assessment into the log; whether anything a view shows changed."""
        body, log = result.result, self.outages
        t = result.timestamp.timestamp()
        disconnected = sorted({self.branch_of(current) for current in body.disconnected})
        events = [
            LineOutageEvent(
                t=t,
                kind=change.kind,
                stations=[current.station for current in change.currents],
                measurements=[current.channel for current in change.currents],
                branches=sorted({self.branch_of(current) for current in change.currents}),
            )
            for change in body.changes
        ]
        changed = bool(events) or disconnected != log.disconnected or log.app_uuid != result.app.uuid
        self.outages = LineOutageLog(
            app_uuid=result.app.uuid,
            app_name=result.app.name,
            window_length=float(result.parameters.get("window_s", 0.0)),
            events=(events[::-1] + log.events)[:OUTAGE_LOG],  # newest first
            disconnected=disconnected,
        )
        return changed

    def branch_of(self, current: MeasuredCurrent) -> str:
        """The branch a current measures, by its ``GridBranch.name``: through its CIM Analog, or, before
        the topology is read (or for a stream with no Analogs), the branch its channel names."""
        if self.topology is not None and current.analog in self.topology.branch_of_analog:
            return self.topology.branch_of_analog[current.analog]
        return current.channel.removeprefix("I_")

    # --- what the panels read -----------------------------------------------

    async def wait_header(self, timeout: float) -> bool:
        """Whether a frame has arrived, waiting up to ``timeout`` seconds for the first."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._header.wait(), timeout)
        return self._header.is_set()

    async def grid(self) -> Topology:
        """The grid, read once from the CIM graph (off the loop), however many ask at once."""
        if self._topology is None or (self._topology.done() and self._topology.exception() is not None):
            loop = asyncio.get_running_loop()
            self._topology = asyncio.ensure_future(loop.run_in_executor(self._cim, read_topology))
        self.topology = await asyncio.shield(self._topology)
        return self.topology

    def statuses(self) -> list[AppStatus]:
        now = time.time()
        return [
            AppStatus(
                uuid=uuid,
                app_name=entry.app_name,
                status=entry.status,
                t=entry.t,
                received_at=entry.received_at,
                stale=now - entry.received_at > STALE_AFTER,
            )
            for _, (uuid, entry) in sorted(self._statuses.items())
        ]

    def feed_status(self) -> FeedStatus:
        header = self.window.header
        return FeedStatus(
            source=SOURCE,
            streaming=self._last_frame_at is not None and time.time() - self._last_frame_at < STREAMING_WITHIN,
            data_rate=header.data_rate if header else 0.0,
            n_channels=header.n_columns if header else 0,
            frames=self.frames,
            error=self.feed.error if self.feed else None,
        )

    # --- waking views -------------------------------------------------------

    @contextlib.contextmanager
    def updates(self, *topics: str, maxsize: int = 64) -> Iterator[asyncio.Queue]:
        """A queue woken by any of ``topics`` and by every ``nudge``, for as long as the view is open."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        view = (queue, frozenset(topics))
        self._views.append(view)
        try:
            yield queue
        finally:
            self._views.remove(view)

    def _wake(self, topic: str) -> None:
        for queue, topics in self._views:
            if topic in topics:
                offer(queue, Event(topic))

    def nudge(self) -> None:
        """Wake every open view: something changed that no module published (an operator action)."""
        for queue, _ in self._views:
            offer(queue)


LIVE = LiveGrid()


async def accept(ws: WebSocket) -> bool:
    """Accept a panel's socket; refuse it (1008) without a usable client id. Every client sees the
    same grid, but a socket still says whose it is, as every socket in this backend does."""
    if read_client_id(ws) is None:
        await refuse_socket(ws)
        return False
    await ws.accept()
    return True


@contextlib.asynccontextmanager
async def lifespan(app):
    """Follow the shared run for as long as the server is up, and read the grid in the background."""
    LIVE.reset()
    follower = asyncio.create_task(LIVE.follow(), name="grid-monitor.follow")
    topology = asyncio.create_task(LIVE.grid(), name="grid-monitor.topology")

    def report(task: asyncio.Task) -> None:
        if not task.cancelled() and task.exception() is not None:
            logger.error("%s failed", task.get_name(), exc_info=task.exception())

    follower.add_done_callback(report)
    topology.add_done_callback(report)
    try:
        yield
    finally:
        for task in (follower, topology):
            task.cancel()
        await asyncio.gather(follower, topology, return_exceptions=True)
