"""The CIM graph app's backend: the grid on its geographic layout, with its breakers, over the one CIM
graph that every module reads and the grid simulation follows (``pswamp_core.cim``).

**This app is the graph's only writer** (``grid.Writer``). It fills the store when the server starts,
in the background, and edits it when a visitor operates the grid; nothing else writes it. So the
graph changes only when this app writes, and there is nothing to watch: after each write the state is
read from the writer's own repository and pushed down every open socket. The graph is shared, not
per client: a breaker opened by any visitor is opened for all of them, and the simulation follows it.

Commands come up over REST (a switch, a line, a reset), each one SPARQL update acknowledged here and
then shown on the socket like any other change; state goes down the socket.

Until the grid is loaded this app answers 503 ("the grid is loading"), and its socket waits for it;
when the grid cannot be had, 503 with the reason, and the socket closes with 1013. The rest of the
server serves as usual either way. Everything that touches the graph
blocks (HTTP to the store, or rdflib), so it runs on one thread of its own, which owns the writer.
"""

import asyncio
import contextlib
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException, WebSocket
from shared import (
    ClientId,
    CommandAck,
    SocketRegistry,
    get_logger,
    read_client_id,
    send_state,
    wait_for_disconnect,
)

from .grid import GridState, Writer, read_layout
from .model import CimGraphState, CimLayout, SwitchBody

logger = get_logger("cim-graph")
router = APIRouter()
sockets = SocketRegistry()


class Graph:
    """The process's writer, on its thread, and the last state it pushed."""

    def __init__(self) -> None:
        self._thread = ThreadPoolExecutor(1, thread_name_prefix="cim-graph")
        self._writer: Writer | None = None
        self._loading: asyncio.Task | None = None
        self._state: GridState | None = None
        self._last: CimGraphState | None = None
        self._layout: CimLayout | None = None

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
            switches=state.switches, out_of_service=sorted(state.out_of_service), writable=self._writer.writable
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
        message = self.message()
        if message != self._last:
            self._last = message
            for client in sockets.clients():
                await sockets.send_to_client(client, message)
        return done

    def stop(self) -> None:
        if self._loading is not None:
            self._loading.cancel()
        self._thread.shutdown(wait=False, cancel_futures=True)


#: Made anew by each lifespan (its thread belongs to that run of the app); the store outlives it.
graph = Graph()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load the grid into the store, in the background, as the server starts."""
    global graph
    graph = Graph()
    graph.load()
    try:
        yield
    finally:
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
# Each is one update of the graph. The simulation and every screen follow the graph, so none of them
# answers with state: the change arrives on the socket like any other.


async def _writable() -> None:
    writer = await graph.ready()
    if not writer.writable:
        raise HTTPException(409, "the graph is read-only: the CGMES profiles are not loaded")


@router.post("/switches/{mrid}", operation_id="cim_graph_set_switch")
async def set_switch(mrid: str, body: SwitchBody, client_id: ClientId) -> CommandAck:
    """Open (``open: true``) or close a switch. 404 for an unknown switch, 409 when it is already so."""
    await _writable()
    state = await graph.known()
    if mrid not in state.switches:
        raise HTTPException(404, f"no switch {mrid}")
    if state.switches[mrid] == body.open:
        raise HTTPException(409, f"{mrid} is already {'open' if body.open else 'closed'}")
    done = await graph.write(Writer.set_switch, mrid, body.open)
    logger.info("client %s: %s", client_id, "; ".join(done))
    return CommandAck(applied="open switch" if body.open else "close switch")


@router.post("/lines/{mrid}", operation_id="cim_graph_set_line")
async def set_line(mrid: str, body: SwitchBody, client_id: ClientId) -> CommandAck:
    """Take a line (or a transformer) out of service (``open: true``) or bring it back: the breakers
    that cut one of its ends off, or, for a line with none, a terminal. 404 for an unknown branch, 409
    when it is already so."""
    await _writable()
    state = await graph.known()
    if mrid not in state.branches:
        raise HTTPException(404, f"no line {mrid}")
    if (mrid in state.out_of_service) == body.open:
        raise HTTPException(409, f"{mrid} is already {'out of' if body.open else 'in'} service")
    done = await graph.write(Writer.set_line, mrid, body.open)
    logger.info("client %s: %s", client_id, "; ".join(done))
    return CommandAck(applied="line out" if body.open else "line in")


@router.post("/reset", operation_id="cim_graph_reset")
async def reset(client_id: ClientId) -> CommandAck:
    """Put the grid back as it was loaded: every switch as the model has it, every branch in service."""
    await graph.ready()
    await graph.write(Writer.reset)
    logger.info("client %s: the grid was reset", client_id)
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
