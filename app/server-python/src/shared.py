"""Helpers shared by the app packages under src/.

Not an app package: it exposes no `router` and is never listed in `APPS` — it is
just the home for pieces every app would otherwise copy. Keep it strictly
domain-free; anything that knows about timelines, PMU records, or any one app's
state belongs in that app's own package.

Most of what an app package needs is *defined* one level down, in `pswamp_web/`,
and re-exported here. That looks backwards and is not:

`pswamp_web/` is kept self-contained — nothing inside it may import from the
rest of this backend — because the repo's two Python projects are meant to become
one, and the direction depends on how long the Qt desktop path lives: either that
package moves in under `pswamp/`, or — once Qt is gone — the root package moves in
here (§7 of `doc/WIP-context-port-from-qt-to-web-frontend.md`). Self-containment
is what keeps either move cheap. The rule is one-way, though — it says nothing
about importing *inward*, which is what this module does, and which stays legal
whichever way the consolidation goes.

Getting that direction right is what removed four "change one, change the other"
duplicates: `ClientId`, `CommandAck`, the client-id parser, and the stdout
logger were each declared twice, and ~90 lines in `api_contract.py` existed to
reunify two of them in the published contract. One definition each now.

So an app package imports from here and needs to know nothing about the layout:

    from shared import ClientId, CommandAck, SocketRegistry, get_logger

What is genuinely defined here is `SocketRegistry` — the scaffold apps' socket
bookkeeping, which `pswamp_web/` has no use for because its pages push from their
own per-connection task rather than fanning out to a client's sockets — and the
edge of the server data architecture (doc/server-data-architecture.md), which
every app over a core pipeline uses:

    transport()           the process's transport, from PSWAMP_TRANSPORT
    serve_pipeline(...)   an app's lifespan: its shared live runs, its errors
                          forwarded to the tray, its modules hosted here when the
                          transport is in-memory, and every run stopped on the way out
    connected_pipeline    a socket's handshake: its client's run, or a close code
    push_changes          one state message on connect and one per change
    dispatch_command      a POST's command into its client's run: 404, 409 or an ack
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable

from errors import HUB
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from pswamp_core.command_routing import CommandRefused
from pswamp_core.host import serve_hosts
from pswamp_core.messages import Command, ErrorEvent
from pswamp_core.pipeline import CapacityError, Pipeline, PipelineRegistry, PipelineRun, start_live_runs
from pswamp_core.subscription import Overflow
from pswamp_core.transport import Transport, transport_from_env
from pswamp_core.util.tasks import cancel_and_wait

from pswamp_web.log import get_logger
from pswamp_web.pump import wait_for_disconnect
from pswamp_web.sessions import SessionRegistry
from pswamp_web.wire import (
    CLIENT_ID_PATTERN,
    ClientId,
    CommandAck,
    read_client_id,
    send_state,
)

__all__ = [
    "CLIENT_ID_PATTERN",
    "COMMAND_RESPONSES",
    "ClientId",
    "CommandAck",
    "SocketRegistry",
    "connected_pipeline",
    "dispatch_command",
    "get_logger",
    "push_changes",
    "read_client_id",
    "send_state",
    "serve_pipeline",
    "transport",
    "wait_for_disconnect",
]

logger = get_logger("shared")


class SocketRegistry(SessionRegistry[WebSocket]):
    """This app's live sockets, per client id.

    A `SessionRegistry` (see `pswamp_web/sessions.py`) whose session *is* the
    socket, which is what a scaffold app's command needs to reach: it changes
    per-client state and the result has to go down whatever sockets that client
    has open. The page packages register something else in the same structure --
    a channel selection, a wake-up queue -- because their pushing is done by a
    task that already holds the socket.

    Pure transport: it knows nothing about what is being sent, so every app keeps
    its own instance beside its own state.

    One client may briefly hold several sockets -- two tabs, or a reconnect
    overlapping the socket it replaces -- so a message goes to all of them, and
    registration is scoped to the connection rather than to the client. The app's
    own per-client state deliberately outlives that: a client that comes back
    resumes where it was.
    """

    @contextlib.asynccontextmanager
    async def connected(self, ws: WebSocket, client_id: str) -> AsyncIterator[None]:
        """Accept one socket and hold it in the registry for as long as it lives.

        The scaffold apps' counterpart to `pswamp_web.hub.connected_hub`, minus
        the pipeline: accept, register, and unregister on the way out however the
        handler ends.
        """
        await ws.accept()
        with self.registered(client_id, ws):
            yield

    async def send_to_client(self, client_id: str, message: BaseModel) -> None:
        """Push one message to every live socket this client holds.

        A pydantic model, not a dict, and sent through `send_state` -- the one
        serialiser in the backend. Two reasons, and the second is the one that
        bites:

        1. The model IS the published schema. Every socket payload in this repo
           is declared as a model and picked up by api_contract.py from its
           package's `WS_MESSAGE`, so a message built as a loose dict would be
           absent from the contract the web client generates its types from.
        2. `send_json` routes through `json.dumps`, which emits bare `NaN` and
           `Infinity` tokens that `JSON.parse` rejects outright. pydantic's
           serialiser does not, given the declared field types.

        A socket that fails mid-send is left to its own handler: the receive loop
        there raises on the next turn and unregisters it. So one dead connection
        cannot break delivery to this client's other sockets, and there is only
        one place a socket is removed from the registry.
        """
        for ws in self.of(client_id):
            with contextlib.suppress(Exception):
                await send_state(ws, message)


# --- the edge of the server data architecture ---------------------------------------

_TRANSPORT: Transport | None = None


def transport() -> Transport:
    """The process's one transport, built on first use from ``PSWAMP_TRANSPORT``."""
    global _TRANSPORT
    if _TRANSPORT is None:
        _TRANSPORT = transport_from_env()
        where = "in this process" if _TRANSPORT.in_process else "in workers"
        logger.info("transport: %s; modules are hosted %s", _TRANSPORT.name, where)
    return _TRANSPORT


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """Close the transport once every app is done with it (a SERVICES entry)."""
    global _TRANSPORT
    try:
        yield
    finally:
        closing, _TRANSPORT = _TRANSPORT, None
        if closing is not None:
            await closing.close()


@contextlib.asynccontextmanager
async def serve_pipeline(pipeline: Pipeline, registry: PipelineRegistry) -> AsyncIterator[None]:
    """An app's lifespan. With the in-memory transport, its modules are hosted
    in this process. Each live source gets its shared run, running until
    shutdown. Its error topic is forwarded to the tray of each client whose run
    an error came from. On the way out every run stops (each says
    ``PipelineClosed``)."""
    link = transport()
    tasks = [asyncio.create_task(_forward_errors(link, pipeline.app, registry), name=f"{pipeline.app}.errors")]
    if link.in_process:
        tasks.append(asyncio.create_task(serve_hosts(pipeline.hosts(link)), name=f"{pipeline.app}.hosts"))
        await asyncio.sleep(0)  # the hosts subscribe before the live runs publish
    live_runs = await start_live_runs(pipeline, link)
    try:
        yield
    finally:
        await registry.stop_all()
        for run in live_runs:
            await run.stop("shutdown")
        await cancel_and_wait(*tasks, ignore=(Exception,))


async def _forward_errors(link: Transport, app: str, registry: PipelineRegistry) -> None:
    """Every ``ErrorEvent`` on ``app``'s error topic, to the tray of each client
    watching the run it came from."""
    with link.subscribe(ErrorEvent, app=app, overflow=Overflow.GROW) as errors:
        async for key, event in errors:
            for client_id in registry.watching(key):
                HUB.publish(client_id, app, event)


@contextlib.asynccontextmanager
async def connected_pipeline(ws: WebSocket, registry: PipelineRegistry) -> AsyncIterator[PipelineRun | None]:
    """Accept a socket and hold its client's run while it lives; ``None`` when refused.

    No usable client id: closed before accepting (1008). At capacity: accepted,
    then closed with 1013, since a close code only reaches the browser on an
    established connection. A run that fails to start: 1011.
    """
    client_id = read_client_id(ws)
    if client_id is None:
        await ws.close(code=1008)
        yield None
        return
    await ws.accept()
    try:
        run = await registry.acquire(client_id)
    except CapacityError:
        logger.warning("refused client %s: all %d runs are in use", client_id, registry.max_runs)
        await ws.close(code=1013)
        yield None
        return
    except Exception:
        logger.exception("the run for client %s failed to start", client_id)
        await ws.close(code=1011)
        yield None
        return
    try:
        yield run
    finally:
        registry.release(client_id)


async def push_changes(ws: WebSocket, run: PipelineRun, build: Callable[[], BaseModel]) -> None:
    """Send ``build()`` now and after every change of ``run``, until the client
    disconnects. A change is a wake-up and the message is built from current
    state, so however much changed meanwhile, one message goes."""
    with run.changes() as changes:
        try:
            await send_state(ws, build())
        except WebSocketDisconnect:
            return

        async def push() -> None:
            async for _ in changes:
                await send_state(ws, build())

        pusher = asyncio.create_task(push())
        try:
            await wait_for_disconnect(ws)
        finally:
            await cancel_and_wait(pusher, ignore=(WebSocketDisconnect,))


#: A command route's answers besides its ack; pass as ``responses=``.
COMMAND_RESPONSES: dict[int | str, dict] = {
    404: {"description": "The client has no running pipeline: its page is not open."},
    409: {"description": "The command does not apply in the pipeline's current state."},
}


def dispatch_command(registry: PipelineRegistry, command: Command, log: logging.Logger) -> CommandAck:
    """Dispatch ``command`` into its client's run and acknowledge it.

    404 when the client has no run (a command never builds one); 409 when the
    player refuses it now, with the reason as the detail. The ack means
    *published*: the effect arrives on the socket.
    """
    client_id = command.client_id or ""
    run = registry.peek(client_id)
    if run is None:
        raise HTTPException(404, f"no running pipeline for client {client_id}; open the page first")
    try:
        run.dispatch(command)
    except CommandRefused as refused:
        log.info("client %s: %s refused: %s", client_id, command.name, refused)
        raise HTTPException(409, str(refused)) from refused
    log.info("client %s: %s (request %s)", client_id, command.name, command.request_id)
    return CommandAck(applied=command.name)
