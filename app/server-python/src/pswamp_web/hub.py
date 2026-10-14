# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""One PMU pipeline per client, and the registry that owns their lifecycle.

Each connected client gets its **own** replay of the recording, starting at 0 s
when it first connects, with its own player, its own application threads and its
own alarm/status/island stores. Nothing about the grid data is shared between
clients any more except the recording itself, which is read-only.

That is a reversal of what this module used to do, and the reasoning is worth
keeping. The earlier arrangement ran one pipeline for the whole process, on the
grounds that there is one grid and two operators seeing different frequencies
would be a bug. True of a control room; false of this, which is a rig for
exploring recorded data. A visitor wants to watch the disturbance from the
beginning, not join someone else's replay half way through — so the useful unit
is one timeline per viewer.

The invariant is therefore now simply: **everything is per client.** The page
packages' ``ClientState`` still holds view state (which channels are selected,
what was last sent); the Hub beside it holds that client's data.

What that costs, and why the registry is not optional: a Hub is **four threads**
and roughly 30 MB of resident memory, and freed memory is not returned to the OS,
so peak RSS follows the *cap* rather than the typical load. Hence
:class:`HubRegistry` — it bounds how many exist, reclaims them when nobody is
watching, and is the only thing allowed to construct one.
"""

import asyncio
import contextlib
import threading
import time
from collections.abc import AsyncIterator

from fastapi import HTTPException, WebSocket

from pswamp.monitoring.islanding import IslandingApp
from pswamp.monitoring.line_outage_detection import LineOutageDetectionApp

from .bus import Bus
from .log import get_logger
from .recorded_io import LabeledRowDecoder, RecordingPlayer
from .replay import (
    ISLANDING_EVAL_HZ,
    ISLANDING_WINDOW_SECONDS,
    WINDOW_SECONDS,
    MeasurementStoreApp,
    load_recording,
)
from .stores import AlarmStore, AppStatusStore, IslandStore, LineOutageStore
from .wire import ReplayStatus, read_client_id, refuse_socket

logger = get_logger("pswamp_web.hub")

# Topic the islanding application's results are published on. Results carry no
# reliable marker of which application produced them, so the source is encoded in
# the topic; status and alarm messages already name their application.
ISLANDING_RESULT_TOPIC = "islanding.result"
LINE_OUTAGE_RESULT_TOPIC = "line_outage.result"

# Topics the applications publish under names of their own; spelled here so a
# page subscribes to the same string the stores listen on.
ALARM_TOPIC = "alarms"

# How many pipelines may exist at once. Sized from memory and the GIL rather than
# CPU time: one pipeline is ~1.4% of a core but ~30 MB that never comes back, and
# every one of its four threads runs Python bytecode contending for the one GIL
# with the event loop that serialises WebSocket messages.
MAX_PIPELINES = 8

# How long a pipeline keeps replaying after its last socket closes. Long enough
# that a reload, a navigation or a flaky network rejoins the same stream; short
# enough that a closed tab gives its slot back within a coffee break.
IDLE_EVICT_SECONDS = 300.0


class CapacityError(RuntimeError):
    """Every pipeline slot is taken by a client that still has a socket open."""


class Hub:
    """Owns one client's replay and applications. Built only by HubRegistry."""

    def __init__(self, client_id: str = "-") -> None:
        # Only ever used to label threads and log lines. The Hub itself does not
        # care whose it is.
        self.client_id = client_id
        self.bus = Bus()
        self.alarms = AlarmStore()
        self.statuses = AppStatusStore()
        self.islands = IslandStore()
        self.line_outages = LineOutageStore()

        self.recording = None
        self.player: RecordingPlayer | None = None
        self.store_app: MeasurementStoreApp | None = None
        self.islanding_app: IslandingApp | None = None
        self.line_outage_app: LineOutageDetectionApp | None = None

        self._threads: list[threading.Thread] = []
        self._detach: list = []
        self._started = False

    # -- lifecycle -----------------------------------------------------------

    def start(self, loop) -> None:
        if self._started:
            return
        try:
            self._start(loop)
        except Exception:
            self.stop()
            raise

    def _start(self, loop) -> None:
        self.bus.bind(loop)

        # Shared across every pipeline and read-only; see load_recording().
        self.recording = load_recording()

        # Fresh player, so this client's replay starts at sample 0 with its own
        # wall-clock base regardless of how long the process has been up.
        self.player = RecordingPlayer(self.recording, speed=1.0, loop=True)

        # One reader per application, all off the same player, so every
        # application sees the same sample at the same instant -- the property a
        # single Kafka topic with independent consumer offsets would give.
        self.store_app = MeasurementStoreApp(
            io=self.player.subscribe(publish=self._publisher()),
            input_decoder=LabeledRowDecoder,
            window_length=WINDOW_SECONDS,
            eval_freq=1,
            app_name="Measurement Store",
        )
        self.islanding_app = IslandingApp(
            io=self.player.subscribe(publish=self._publisher(ISLANDING_RESULT_TOPIC)),
            input_decoder=LabeledRowDecoder,
            window_length=ISLANDING_WINDOW_SECONDS,
            eval_freq=ISLANDING_EVAL_HZ,
        )

        # Line outage detection reads current magnitudes, which the other
        # applications ignore. It is silent unless a branch changes state, so it
        # costs almost nothing when the grid is intact.
        # No detection parameters passed: threshold, window and evaluation rate
        # are the application's own defaults and belong to it, not to this
        # transport layer. Passing copies of them here would silently pin today's
        # values if they were ever retuned upstream.
        self.line_outage_app = LineOutageDetectionApp(
            io=self.player.subscribe(publish=self._publisher(LINE_OUTAGE_RESULT_TOPIC)),
            input_decoder=LabeledRowDecoder,
        )

        self.islands.attach(self.islanding_app)
        self._attach_stores()

        # Applications first, player second. Each application already has its
        # pre-filled window sitting in its reader queue, so it has work to do
        # immediately; starting the player first would leave it publishing into
        # queues nobody is draining yet, and the first samples would be dropped
        # as though a consumer were lagging.
        for app in (self.store_app, self.islanding_app, self.line_outage_app):
            app.run_in_thread()
            # run_in_thread names them "Thread-N (run)", and the player calls
            # itself "RecordingPlayer" in every pipeline. With one pipeline that
            # was merely unhelpful; with one per client a thread dump at the cap
            # is 32 indistinguishable rows, so label them by owner.
            app.runner_thread.name = f"pswamp[{self.client_id}]-{app.app_name}"
            self._threads.append(app.runner_thread)
        self.player.start()

        self._started = True

    def stop(self) -> None:
        """Tear down, newest-dependency-first. Called off the event loop."""
        for app in (self.line_outage_app, self.islanding_app, self.store_app):
            if app is not None:
                app.stop()
        if self.player is not None:
            # Wakes any application blocked waiting for the next frame: the read
            # times out, sees the player has stopped, and raises StopIteration,
            # which SnapshotApp already treats as end-of-stream.
            self.player.stop()
        for thread in self._threads:
            thread.join(timeout=2.0)
            if thread.is_alive():
                logger.warning(
                    "application thread %s did not stop in time", thread.name
                )
        self._threads.clear()

        for detach in self._detach:
            detach()
        self._detach.clear()

        self.bus.bind(None)
        self._started = False

    def dead_threads(self) -> list[str]:
        """Names of application threads that have exited while we were running.

        ``SnapshotApp.run`` has no exception handling and p-SWAMP logs nothing,
        so a failing application dies silently. With one pipeline that was an
        outage somebody noticed; with one per client it is a single client's
        panel quietly freezing, which nobody reports. The registry checks this so
        it at least reaches the log.
        """
        if not self._started:
            return []
        return [t.name for t in self._threads if not t.is_alive()]

    # -- internals -----------------------------------------------------------

    def _publisher(self, result_topic: str | None = None):
        """Build the publish callback handed to one application's reader.

        Called from that application's own thread, so everything it does must be
        thread-safe; publishing to the bus is, by construction.
        """
        bus = self.bus

        def publish(topic: str, payload: object) -> None:
            if topic == "result" and result_topic is not None:
                topic = result_topic
            elif topic == "result":
                return  # an application whose results nothing subscribes to
            bus.publish_threadsafe(topic, payload)

        return publish

    def _attach_stores(self) -> None:
        """Feed the alarm and status stores from the bus, for the process
        lifetime. Both are pure state, so they consume synchronously rather than
        through a queue they would have to be drained from."""
        self._detach = [
            self.bus.add_listener("status", self.statuses.handle),
            self.bus.add_listener(ALARM_TOPIC, self.alarms.handle),
            self.bus.add_listener(ISLANDING_RESULT_TOPIC, self.islands.handle),
            self.bus.add_listener(LINE_OUTAGE_RESULT_TOPIC, self.line_outages.handle),
        ]

    # -- read-side helpers ---------------------------------------------------

    def replay_status(self) -> ReplayStatus:
        player, recording = self.player, self.recording
        if player is None or recording is None:
            return ReplayStatus(
                source="",
                playing=False,
                data_rate=0,
                n_samples=0,
                n_channels=0,
                cursor=0,
                position=0.0,
                duration=0.0,
            )
        cursor = player.cursor
        return ReplayStatus(
            source=recording.source,
            playing=not player.stopped,
            data_rate=recording.data_rate,
            n_samples=recording.n_samples,
            n_channels=recording.n_channels,
            cursor=cursor,
            position=(cursor % recording.n_samples) / recording.data_rate,
            duration=recording.duration,
        )


class _Entry:
    """One client's pipeline, plus the bookkeeping that decides its fate."""

    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.sockets = 0  # live WebSockets; 0 means evictable
        self.last_used = time.monotonic()
        self.evict_task: asyncio.Task | None = None


class HubRegistry:
    """Creates, hands out and reclaims per-client pipelines.

    The only thing that constructs a :class:`Hub`. Three rules it enforces:

    * **One pipeline per client, however many sockets.** The grid monitor opens
      five at once, so five ``acquire`` calls for a client that has no pipeline
      yet arrive together. A per-client lock is what makes them build one
      pipeline instead of five — this is the single sharpest edge in here.
    * **A pipeline outlives its sockets, briefly.** Closing the last one starts
      an idle timer rather than tearing down, so a reload rejoins the same
      stream. Reconnecting cancels the timer.
    * **Never more than the cap, even mid-build.** At the cap a new client
      reclaims the least-recently-used pipeline that nobody is watching; if every
      one is in use, the connection is refused rather than the machine
      oversubscribed. Pipelines still under construction count against the cap
      too (``_pending``), so a burst of distinct clients connecting at once cannot
      each see room and overshoot it together.

    Everything here runs on the event loop, so ``_entries`` needs no lock of its
    own — the per-client locks exist to bracket the *awaits* inside ``acquire``,
    not to protect the dict.
    """

    def __init__(
        self,
        *,
        max_pipelines: int = MAX_PIPELINES,
        idle_seconds: float = IDLE_EVICT_SECONDS,
    ) -> None:
        self._entries: dict[str, _Entry] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        # In-flight acquire() calls per client, incremented *before* the client's
        # lock is taken so a caller merely queued on the lock counts too. A
        # client's lock is reclaimable only while this is zero; see
        # _drop_lock_if_unused, which is what keeps the idle path from leaking one
        # lock per distinct client id ever seen.
        self._acquiring: dict[str, int] = {}
        # Pipelines past the capacity check in _make_room but not yet registered
        # in _entries. Counted against the cap so a burst of distinct clients
        # cannot all pass the check during each other's ~40-50 ms construction
        # window and collectively blow past MAX_PIPELINES (and the pod memory
        # limit sized from it).
        self._pending = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self.max_pipelines = max_pipelines
        self.idle_seconds = idle_seconds

    def bind(self, loop: asyncio.AbstractEventLoop | None) -> None:
        self._loop = loop

    @property
    def live(self) -> int:
        return len(self._entries)

    def peek(self, client_id: str) -> Hub | None:
        """This client's pipeline if it already has one, else None.

        A pure read: no socket count, no idle timer, nothing constructed. It is
        what a *command* uses, and the distinction from :meth:`acquire` is the
        point -- see :func:`live_hub` below.
        """
        entry = self._entries.get(client_id)
        return None if entry is None else entry.hub

    @contextlib.asynccontextmanager
    async def session(self, client_id: str) -> AsyncIterator[Hub]:
        """Hold a client's pipeline for the life of one WebSocket.

        Every endpoint goes through this rather than calling acquire/release, so
        the release cannot be skipped when its receive loop ends or another
        exception unwinds the endpoint.
        """
        hub = await self.acquire(client_id)
        try:
            yield hub
        finally:
            self.release(client_id)

    async def acquire(self, client_id: str) -> Hub:
        # Count this acquire before taking the lock, so a caller still queued on
        # the lock keeps that lock from being reclaimed out from under it. The
        # matching decrement is in the finally; _drop_lock_if_unused does the
        # reclaiming.
        self._acquiring[client_id] = self._acquiring.get(client_id, 0) + 1
        try:
            lock = self._locks.setdefault(client_id, asyncio.Lock())
            async with lock:
                entry = self._entries.get(client_id)
                if entry is not None:
                    # Cancel the pending eviction *inside* the lock. If the evictor
                    # already started, it holds this lock and we waited for it — so
                    # we find no entry below and build a fresh pipeline, rather than
                    # handing back one that is being torn down.
                    if entry.evict_task is not None:
                        entry.evict_task.cancel()
                        entry.evict_task = None
                    entry.sockets += 1
                    entry.last_used = time.monotonic()
                    self._report_dead_threads(client_id, entry.hub)
                    return entry.hub

                await self._make_room()

                # Reserve the slot *before* the await below. _make_room left room
                # for exactly one more counting live + pending; claim it now, while
                # still on the loop, so a concurrent acquire for a different client
                # sees the reservation and does not also build. Released in the
                # finally whether construction succeeds or raises.
                self._pending += 1
                try:
                    hub = Hub(client_id=client_id)
                    # Off the loop: start() constructs three applications and
                    # prefills their windows (~40-50 ms of blocking work). On the
                    # loop that would stall every other client's push task.
                    await asyncio.to_thread(hub.start, self._loop)

                    entry = _Entry(hub)
                    entry.sockets = 1
                    self._entries[client_id] = entry
                finally:
                    self._pending -= 1
                logger.info(
                    "pipeline started for client %s (%s/%s live)",
                    client_id,
                    self.live,
                    self.max_pipelines,
                )
                return hub
        finally:
            self._acquiring[client_id] -= 1
            self._drop_lock_if_unused(client_id)

    def release(self, client_id: str) -> None:
        entry = self._entries.get(client_id)
        if entry is None:
            return
        entry.sockets = max(0, entry.sockets - 1)
        entry.last_used = time.monotonic()
        if entry.sockets == 0 and entry.evict_task is None:
            entry.evict_task = asyncio.create_task(self._evict_when_idle(client_id))

    async def stop_all(self) -> None:
        """Tear down every pipeline, on process shutdown.

        Concurrently: one ``Hub.stop`` is ~0.5 s of joining threads and can be
        8 s in the worst case, so doing them in sequence would make shutdown at
        the cap take longer than most orchestrators wait before sending SIGKILL.
        """
        client_ids = list(self._entries)
        for client_id in client_ids:
            entry = self._entries.get(client_id)
            if entry is not None and entry.evict_task is not None:
                entry.evict_task.cancel()
        entries = [self._entries.pop(cid) for cid in client_ids]
        self._locks.clear()
        if not entries:
            return
        await asyncio.gather(
            *(asyncio.to_thread(entry.hub.stop) for entry in entries),
            return_exceptions=True,
        )
        logger.info("stopped %s pipeline(s)", len(entries))

    # -- internals -----------------------------------------------------------

    async def _make_room(self) -> None:
        """Free a slot if we are at the cap. Caller holds the new client's lock.

        Counts pipelines still under construction (``_pending``) as well as live
        ones, so simultaneous first-connects from distinct clients cannot each see
        room and collectively overshoot the cap — leaving room for the one slot
        the caller reserves right after this returns.

        Note this evicts *another* client's pipeline while holding ours. That is
        the only place two clients' bookkeeping is touched at once, and it is
        deadlock-free because it never waits on the victim's lock — ``Hub.stop``
        is idempotent, so racing with the victim's own idle evictor is harmless.
        """
        while self.live + self._pending >= self.max_pipelines:
            victim = min(
                (cid for cid, e in self._entries.items() if e.sockets == 0),
                key=lambda cid: self._entries[cid].last_used,
                default=None,
            )
            if victim is None:
                raise CapacityError(f"all {self.max_pipelines} pipelines are in use")
            await self._evict(victim, "capacity")

    async def _evict_when_idle(self, client_id: str) -> None:
        try:
            await asyncio.sleep(self.idle_seconds)
        except asyncio.CancelledError:
            return
        lock = self._locks.get(client_id)
        if lock is None:
            return
        async with lock:
            entry = self._entries.get(client_id)
            # A client may have reconnected while we waited for the lock.
            if entry is None or entry.sockets > 0:
                return
            await self._evict(client_id, "idle")

    async def _evict(self, client_id: str, reason: str) -> None:
        entry = self._entries.pop(client_id, None)
        # Reclaim the client's lock now its pipeline is gone. Keyed on _acquiring
        # rather than lock.locked(): the idle evictor calls this while *holding*
        # the lock, so lock.locked() is True on the very path that most needs the
        # lock dropped — which is how the lock used to leak one entry per distinct
        # client id. _acquiring stays > 0 exactly while a concurrent connect still
        # needs this same lock object (a queued waiter counts), so the lock is
        # dropped only when nothing is racing to rebuild it.
        self._drop_lock_if_unused(client_id)
        if entry is None:
            return
        if entry.evict_task is not None:
            entry.evict_task = None
        # A fresh Hub is always built on the next connect; a stopped one is never
        # restarted. It would resume from its old cursor rather than 0, and its
        # readers are still registered with a player that has been shut down.
        await asyncio.to_thread(entry.hub.stop)
        logger.info(
            "pipeline evicted for client %s (%s), %s/%s live",
            client_id,
            reason,
            self.live,
            self.max_pipelines,
        )

    def _drop_lock_if_unused(self, client_id: str) -> None:
        """Reclaim a client's per-client lock once nothing needs it.

        "Nothing needs it" is: no ``acquire`` for this client is in flight or
        queued (``_acquiring`` is zero) *and* it has no live pipeline. While an
        acquire is outstanding the lock object must not change — two acquires that
        serialised on two *different* locks would each find no entry and build a
        pipeline apiece, orphaning four threads. ``_acquiring`` is incremented
        before the lock is taken, so a caller merely *waiting* on the lock still
        counts; that is what makes it safe to drop the lock even from the idle
        evictor, which calls this while holding the lock itself.
        """
        if self._acquiring.get(client_id, 0) <= 0:
            self._acquiring.pop(client_id, None)
            if client_id not in self._entries:
                self._locks.pop(client_id, None)

    def _report_dead_threads(self, client_id: str, hub: Hub) -> None:
        dead = hub.dead_threads()
        if dead:
            logger.error(
                "client %s has dead application thread(s): %s",
                client_id,
                ", ".join(dead),
            )


REGISTRY = HubRegistry()


def live_hub(client_id: str) -> Hub:
    """The pipeline a command applies to, or 404.

    The REST counterpart of :func:`connected_hub`, and deliberately the weaker
    one: a command **must never build a pipeline**. Four threads and ~30 MB
    against MAX_PIPELINES is a cost only a viewer should be able to incur, and a
    POST has no socket to deliver the results to anyway -- it would start a replay
    that nobody is watching and that would then have to idle out.

    So a command to a client with no live pipeline is a 404, not an implicit
    start. In practice that means "you have no page open", which is exactly what
    it should mean.
    """
    hub = REGISTRY.peek(client_id)
    if hub is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"no live pipeline for client {client_id}; "
                "open the page (and its WebSocket) before sending commands"
            ),
        )
    return hub


@contextlib.asynccontextmanager
async def connected_hub(ws: WebSocket) -> AsyncIterator[Hub | None]:
    """Accept one socket and hold its client's pipeline for as long as it lives.

    Every page endpoint opens with this, so the identify-accept-acquire preamble
    and the matching release exist once rather than five times. Yields ``None``
    when the connection was refused, which the caller returns on::

        async with connected_hub(ws) as hub:
            if hub is None:
                return

    Two refusals, both accepted *first* and then closed, because a code only
    reaches the browser on an established connection:

    * **No usable client id** -- closed with 1008 (``refuse_socket``). Our own
      client always sends one, so this is a caller that has no business here.
    * **At capacity** -- closed with 1013.

    The web client treats both codes as terminal and stops reconnecting, which
    is the whole reason to spend a handshake on saying no politely.
    """
    client_id = read_client_id(ws)
    if client_id is None:
        await refuse_socket(ws)
        yield None
        return

    await ws.accept()
    try:
        hub = await REGISTRY.acquire(client_id)
    except CapacityError:
        logger.warning(
            "refused client %s: all %s pipelines in use",
            client_id,
            REGISTRY.max_pipelines,
        )
        await ws.close(code=1013)  # try again later
        yield None
        return
    except Exception:
        logger.exception("failed to start pipeline for client %s", client_id)
        await ws.close(code=1011)  # unexpected server error
        yield None
        return

    try:
        yield hub
    finally:
        REGISTRY.release(client_id)
