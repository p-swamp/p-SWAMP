"""The CIM graph app's backend: the grid on its geographic layout, with its breakers, over the one CIM
graph that every module reads and the grid simulation follows (``pswamp_core.cim``).

**This app is the graph's only writer** (``grid.Writer``). It fills the store when the server starts,
in the background, and writes what the live simulation reports it did (``CimEdits`` from its shared
run, ADR-016): a breaker it opened, the terminal of a line it took out. Nothing else writes it. It also
keeps the latest SCADA values the simulation scans (``ScadaScan``), each scan replacing the last, in a
graph of their own that does not move the version stamp (ADR-017); a reset forgets them.

**A visitor operates the grid through the simulation**, not the graph: a breaker or a line is a
command to it (``shared.dispatch_live``), and the graph shows the result once the simulation has
reported it. Without the simulation (a deployment that does not run it), the grid cannot be
operated (503); a reset still puts the graph back. So the
graph changes only when this app writes, and there is nothing to watch: after each write the state is
read from the writer's own repository and pushed down every open socket. The graph is shared, not
per client: a breaker opened by any visitor is opened for all of them, and the simulation follows it.

Commands come up over REST (a switch, a line, a reset), each acknowledged once the simulation has
taken it, and shown on the socket like any other change; state goes down the socket. So do the
**disturbances** (a branch trip, a short circuit, a fault cleared by protection, a load step), which
go to the simulation only: the graph learns only of what protection does about them. What the
simulation announces (``SimEvent``) is kept, the most recent ``EVENTS``, and is part of the state the
socket pushes, which is the only place a person hears of a disturbance.

Until the grid is loaded this app answers 503 ("the grid is loading"), and its socket waits for it;
when the grid cannot be had, 503 with the reason, and the socket closes with 1013. The rest of the
server serves as usual either way. Everything that touches the graph
blocks (HTTP to the store, or rdflib), so it runs on one thread of its own, which owns the writer.
"""

import asyncio
import collections
import contextlib
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException, WebSocket
from pswamp_core.subscription import Overflow
from pswamp_core.util.tasks import cancel_and_wait
from pswamp_models.cim import CimEdits
from pswamp_models.scada import ScadaScan
from pswamp_models.rtsim import (
    ClearShortCircuitCommand,
    FaultAndClearCommand,
    LoadStepCommand,
    OperateLineCommand,
    OperateSwitchCommand,
    ReconnectBranchCommand,
    ResetSimulationCommand,
    ShortCircuitCommand,
    SimEvent,
    TripBranchCommand,
)
from shared import (
    LIVE_RUNS,
    ClientId,
    CommandAck,
    SocketRegistry,
    dispatch_live,
    get_logger,
    read_client_id,
    send_state,
    transport,
    wait_for_disconnect,
)

from .grid import GridState, Writer, read_layout
from .model import CimGraphState, CimLayout, FaultBody, LoadStepBody, ShortCircuitBody, SwitchBody

logger = get_logger("cim-graph")
router = APIRouter()
sockets = SocketRegistry()

#: The live simulation of the graph: the app whose pipeline runs it, and the source's name there.
SIMULATION = ("pmu-test-streamer", "rtsim")
#: How many of the simulation's announcements the state carries.
EVENTS = 50


class Graph:
    """The process's writer, on its thread, and the last state it pushed."""

    def __init__(self) -> None:
        self._thread = ThreadPoolExecutor(1, thread_name_prefix="cim-graph")
        self._writer: Writer | None = None
        self._loading: asyncio.Task | None = None
        self._state: GridState | None = None
        self._last: CimGraphState | None = None
        self._layout: CimLayout | None = None
        #: What the simulation announced most recently, oldest first.
        self._events: collections.deque[SimEvent] = collections.deque(maxlen=EVENTS)

    async def _run(self, function, *args):
        return await asyncio.get_running_loop().run_in_executor(self._thread, function, *args)

    def load(self) -> None:
        """Start loading the grid into the store, in the background (once)."""
        if self._loading is None:
            self._loading = asyncio.ensure_future(self._load())

    async def _load(self) -> None:
        self._writer = await self._run(Writer)
        self._state = await self._run(self._writer.state)
        logger.info("the grid is loaded: %d switches, %d branches", len(self._state.switches), len(self._state.branches))

    async def loaded(self) -> Writer:
        """The writer, once the grid is loaded, waiting for it if need be; what loading raised, if it failed."""
        self.load()
        await asyncio.shield(self._loading)
        return self._writer

    async def ready(self) -> Writer:
        """The writer, once the grid is loaded. ``HTTPException`` 503, with the reason, until then
        or when the grid cannot be had."""
        self.load()
        if not self._loading.done():
            raise HTTPException(503, "the grid is loading")
        error = self._loading.exception()
        if error is not None:
            raise HTTPException(503, f"the grid is not available: {error}")
        return self._writer

    def message(self) -> CimGraphState:
        state = self._state
        return CimGraphState(
            switches=state.switches,
            out_of_service=sorted(state.out_of_service),
            writable=self._writer.writable,
            events=list(self._events),
        )

    async def known(self) -> GridState:
        await self.ready()
        return self._state

    async def current(self) -> CimGraphState:
        await self.ready()
        return self.message()

    async def layout(self) -> CimLayout:
        writer = await self.ready()
        if self._layout is None:
            self._layout = await self._run(read_layout, writer.repo)
        return self._layout

    async def write(self, function, *args):
        """Run ``function(writer, *args)`` on the graph's thread, then push the state it led to."""
        writer = await self.ready()

        def write():
            done = function(writer, *args)
            return done, writer.state()

        done, self._state = await self._run(write)
        await self._push()
        return done

    async def announce(self, event: SimEvent) -> None:
        """Keep what the simulation announced, and push it (the grid is loaded)."""
        await self.loaded()
        self._events.append(event)
        await self._push()

    async def _push(self) -> None:
        message = self.message()
        if message != self._last:
            self._last = message
            for client in sockets.clients():
                await sockets.send_to_client(client, message)

    def stop(self) -> None:
        if self._loading is not None:
            self._loading.cancel()
        self._thread.shutdown(wait=False, cancel_futures=True)


#: Made anew by each lifespan (its thread belongs to that run of the app); the store outlives it.
graph = Graph()


async def _write_reports() -> None:
    """Write what the simulation reports (``CimEdits``) as it comes, once the grid is loaded. A report
    that cannot be written (a producer or a property not allowed, an object the graph does not have)
    is logged and dropped: the simulation goes on, and the graph keeps what it knows."""
    app, source = SIMULATION
    with transport().subscribe(CimEdits, app=app, key=f"live.{source}", overflow=Overflow.GROW) as reports:
        async for _, report in reports:
            try:
                await graph.loaded()
                done = await graph.write(Writer.apply, report)
            except (PermissionError, LookupError) as refused:
                logger.warning("%s reported what is not written: %s", report.producer, refused)
                continue
            except Exception:  # the grid is not available: nothing to write to
                logger.exception("%s reported what could not be written", report.producer)
                continue
            logger.info("%s (%s): %s", report.producer, report.cause, "; ".join(done))


async def _write_scans() -> None:
    """Keep the latest SCADA scan in the graph (``Writer.write_scan``), once the grid is loaded. Only
    the latest matters: a scan that comes while one is written replaces any still waiting."""
    app, source = SIMULATION
    with transport().subscribe(ScadaScan, app=app, key=f"live.{source}", overflow=Overflow.DROP_OLDEST, maxsize=1) as scans:
        async for _, scan in scans:
            try:
                writer = await graph.loaded()
                written, left_out = await graph._run(writer.write_scan, scan)
            except Exception:  # the grid is not available: nothing to write to
                logger.exception("a SCADA scan of %s could not be written", scan.source)
                continue
            if left_out:
                logger.warning("a SCADA scan of %s: %d values written, %d for no SCADA measurement of the grid", scan.source, written, left_out)


async def _relay_events() -> None:
    """Show what the simulation announces (``SimEvent``: a disturbance, a protection operating) on
    every socket, as part of the state, once the grid is loaded."""
    app, source = SIMULATION
    with transport().subscribe(SimEvent, app=app, key=f"live.{source}", overflow=Overflow.GROW) as events:
        async for _, event in events:
            try:
                await graph.announce(event)
            except Exception:  # the grid is not available: no state to show it in
                logger.exception("the simulation's %s of %s could not be shown", event.kind, event.mRID)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load the grid into the store, in the background, as the server starts; write what the
    simulation reports and the latest SCADA scan, and show what it announces."""
    global graph
    graph = Graph()
    graph.load()
    writing = asyncio.create_task(_write_reports(), name="cim-graph.reports")
    relaying = asyncio.create_task(_relay_events(), name="cim-graph.events")
    scanning = asyncio.create_task(_write_scans(), name="cim-graph.scans")
    try:
        yield
    finally:
        await cancel_and_wait(scanning, ignore=(Exception,))
        await cancel_and_wait(relaying, ignore=(Exception,))
        await cancel_and_wait(writing, ignore=(Exception,))
        loading = graph._loading
        graph.stop()
        if loading is not None:
            with contextlib.suppress(BaseException):
                await loading


# --- the static layout --------------------------------------------------------------


@router.get("/layout", operation_id="cim_graph_layout")
async def layout() -> CimLayout:
    """Where the substations, lines and breakers are, from the graph's GL profile."""
    return await graph.layout()


# --- REST commands -------------------------------------------------------------------
#
# Each is a command to the simulation, checked first against what the graph knows. None answers with
# state: the change arrives on the socket once the simulation has reported it and it is written.


def _operate(command, client_id: str) -> CommandAck:
    app, source = SIMULATION
    return dispatch_live(app, source, command.model_copy(update={"client_id": client_id}), logger)


async def _writable() -> None:
    writer = await graph.ready()
    if not writer.writable:
        raise HTTPException(409, "the graph is read-only: the CGMES profiles are not loaded")


@router.post("/switches/{mrid}", operation_id="cim_graph_set_switch")
async def set_switch(mrid: str, body: SwitchBody, client_id: ClientId) -> CommandAck:
    """Open (``open: true``) or close a switch, in the simulation. 404 for an unknown switch, 409 when
    the graph says it is already so, or the simulation refuses; 503 without the simulation."""
    await _writable()
    state = await graph.known()
    if mrid not in state.switches:
        raise HTTPException(404, f"no switch {mrid}")
    if state.switches[mrid] == body.open:
        raise HTTPException(409, f"{mrid} is already {'open' if body.open else 'closed'}")
    return _operate(OperateSwitchCommand(mRID=mrid, open=body.open), client_id)


@router.post("/lines/{mrid}", operation_id="cim_graph_set_line")
async def set_line(mrid: str, body: SwitchBody, client_id: ClientId) -> CommandAck:
    """Take a line out of service (``open: true``) or bring it back, in the simulation: by the one
    breaker that operates it, or, for a line with none, by its terminal. 404 for an unknown branch,
    409 when the graph says it is already so, or the simulation refuses; 503 without the simulation."""
    await _writable()
    state = await graph.known()
    if mrid not in state.branches:
        raise HTTPException(404, f"no line {mrid}")
    if (mrid in state.out_of_service) == body.open:
        raise HTTPException(409, f"{mrid} is already {'out of' if body.open else 'in'} service")
    breaker = next((branch.breaker for branch in (await graph.layout()).branches if branch.mrid == mrid), None)
    if breaker is not None:
        return _operate(OperateSwitchCommand(mRID=breaker, open=body.open), client_id)
    return _operate(OperateLineCommand(mRID=mrid, in_service=not body.open), client_id)


# --- disturbances ---------------------------------------------------------------------
#
# Each goes to the simulation only (ADR-016): the graph never hears of it, and the frames show it. What
# protection does about one (a breaker it opens) is reported like any operation, and written. The
# simulation knows its objects, so it is the one that refuses an object it does not have (409).


@router.post("/branches/{mrid}/trip", operation_id="cim_graph_trip_branch")
async def trip_branch(mrid: str, client_id: ClientId) -> CommandAck:
    """A line or transformer trips, as no one commanded it. 409 for one the simulation does not have;
    503 without the simulation."""
    return _operate(TripBranchCommand(mRID=mrid), client_id)


@router.post("/branches/{mrid}/reconnect", operation_id="cim_graph_reconnect_branch")
async def reconnect_branch(mrid: str, client_id: ClientId) -> CommandAck:
    """A tripped line or transformer comes back. 409 for one the simulation does not have; 503
    without the simulation."""
    return _operate(ReconnectBranchCommand(mRID=mrid), client_id)


@router.post("/nodes/{mrid}/short-circuit", operation_id="cim_graph_short_circuit")
async def short_circuit(mrid: str, body: ShortCircuitBody, client_id: ClientId) -> CommandAck:
    """A short circuit at a connectivity node, until it is cleared. 409 for a node the simulation
    does not have (one cut off from the grid); 503 without the simulation."""
    return _operate(ShortCircuitCommand(mRID=mrid, y=body.y), client_id)


@router.post("/nodes/{mrid}/clear-short-circuit", operation_id="cim_graph_clear_short_circuit")
async def clear_short_circuit(mrid: str, client_id: ClientId) -> CommandAck:
    """The short circuit at a connectivity node goes. 409 for a node the simulation does not have;
    503 without the simulation."""
    return _operate(ClearShortCircuitCommand(mRID=mrid), client_id)


@router.post("/lines/{mrid}/fault", operation_id="cim_graph_fault_line")
async def fault_line(mrid: str, body: FaultBody, client_id: ClientId) -> CommandAck:
    """A fault at one end of a line, cleared after ``clear_ms`` by its protection, which opens the
    breakers that isolate the line; those the graph then shows open. 409 for a line the simulation
    does not have; 503 without the simulation."""
    return _operate(FaultAndClearCommand(mRID=mrid, end=body.end, clear_ms=body.clear_ms, y=body.y), client_id)


@router.post("/loads/{mrid}/step", operation_id="cim_graph_load_step")
async def load_step(mrid: str, body: LoadStepBody, client_id: ClientId) -> CommandAck:
    """A load draws other power, as no one told the graph. 409 for a load the simulation does not
    have; 503 without the simulation."""
    return _operate(LoadStepCommand(mRID=mrid, p_mw=body.p_mw, q_mvar=body.q_mvar), client_id)


@router.post("/reset", operation_id="cim_graph_reset")
async def reset(client_id: ClientId) -> CommandAck:
    """Put the grid back as it was loaded: every switch as the model has it, every branch in service;
    and the simulation, when it runs, starts over from it, every disturbance gone."""
    await graph.ready()
    await graph.write(Writer.reset)
    logger.info("client %s: the grid was reset", client_id)
    app, source = SIMULATION
    if (app, source) in LIVE_RUNS:
        _operate(ResetSimulationCommand(), client_id)
    return CommandAck(applied="reset")


# --- websocket endpoint (downstream only) -----------------------------------


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    client_id = read_client_id(ws)
    if client_id is None:
        await ws.close(code=1008)  # policy violation
        return
    try:
        await graph.loaded()  # a socket opened while the grid loads waits for it
        first = await graph.current()
    except Exception:  # the grid is not available; the reason is in the log
        await ws.close(code=1013)  # try again later
        return

    async with sockets.connected(ws, client_id):
        logger.info("client %s: connected", client_id)
        await send_state(ws, first)
        await wait_for_disconnect(ws)
    logger.info("client %s: disconnected", client_id)
