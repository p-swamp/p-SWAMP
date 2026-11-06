# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``Controller``: the graph as LazyCIM's ``LiveTops``, steering the simulation in the engine's process.

``LiveTops`` exports the graph as a TOPS model, builds a shadow of the system the engine steps, and,
when the graph changes, decides what that means for a running simulation: a switch opened, a line
disconnected, a load's power or a machine's set-point moved, or a model to build again. Through a
``RemoteRunner`` (``runner``) each of those goes to the engine as a message, and the engine's state
comes back for ``LiveTops`` to read.

``changes()`` looks at the graph's version stamp (``pswamp_core.cim.GraphVersion``: one tiny query)
and, only when it moved, marks the profiles that change stale (SSH and SV) and has ``LiveTops``
follow the graph (LazyCIM's ``refresh``, which reads those again and nothing else). When the stamp
has not moved it reads nothing else.

``command()`` applies one of the source's commands (ADR-015). An operation (a switch; the terminal
of a line that has no breaker) goes to the engine, and once a frame has run since, ``reports()``
gives it as ``CimEdits``: what the graph's one writer should now write. A disturbance (a branch
tripped or reconnected, a short circuit, a load step) goes to the engine only. Both are announced,
at once, as a ``SimEvent``. A reset starts the simulation over from the graph. A fault on a line
is put on now and cleared by the breakers that isolate the line, on the engine's clock; and every
look at the graph also runs the protection (``protection``) on the engine's latest state: a line
over its current limit for long enough is tripped by its breakers. What protection opens is
reported as an operation is, its cause ``protection``.

``ControllerProcess`` runs one in a process of its own, over a shared store: a refresh is a second
or so of Python, which would hold up everything else in the server's process.
"""

from __future__ import annotations

import multiprocessing
import time
from collections.abc import Callable
from typing import Any

from lazycim.sim.tops_live import LiveTops
from pswamp_core.cim import CimSettings, GraphVersion, connect_reader, open_store, refresh_expired
from pswamp_core.command_routing import CommandRefused
from pswamp_core.util.time import utcnow
from pswamp_models.cim import CimEdit, CimEdits
from pswamp_models.common import Command, DataModel
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

from .engine import EXPORT
from .pmu import read_analogs
from .protection import Overload, ProtectionSettings
from .runner import RemoteRunner, follow, restart

__all__ = ["COMMANDS", "PRODUCER", "Controller", "ControllerProcess"]

#: What the simulation says it is, as the producer of its ``CimEdits``.
PRODUCER = "rtsim"
#: The commands the controller applies.
COMMANDS: tuple[type[Command], ...] = (
    OperateSwitchCommand,
    OperateLineCommand,
    TripBranchCommand,
    ReconnectBranchCommand,
    ShortCircuitCommand,
    ClearShortCircuitCommand,
    FaultAndClearCommand,
    LoadStepCommand,
    ResetSimulationCommand,
)
#: What a ``SimEvent`` of the simulation as a whole (a reset) is about.
STREAM_ID = "rtsim-from-cim"

class Controller:
    """``repo``, a reader's repository over the graph, simulated by ``LiveTops`` (exported with
    ``EXPORT``, stepped every ``dt`` simulated seconds), protected as ``protection`` says, and
    followed when ``version`` (the graph's stamp, watched from before the export) says it changed.
    For one thread."""

    def __init__(self, repo, version: GraphVersion, *, dt: float, protection: ProtectionSettings | None = None) -> None:
        self.version = version
        self.live = LiveTops.from_repo(repo, dt=dt, **EXPORT)
        self.runner: RemoteRunner | None = None
        self.protection = protection or ProtectionSettings()
        self._overload = Overload(self.protection)
        #: Each protected line end's permanent current limit, A: ``{(line mRID, end): amperes}``.
        self.limits = self._limits()
        self._built = 0
        #: What is to be done at a time on ``LiveTops``'s clock: a fault's clearing, in this process.
        self._timers: list[tuple[float, Callable[[], list[DataModel]]]] = []
        #: The lines protection has tripped, which it does not trip again.
        self._tripped: set[str] = set()
        #: Why each switch the simulation operated was operated, until it is reported: by mRID.
        self._causes: dict[str, tuple[str, str | None]] = {}
        #: Operations of a line's terminal not yet reported: the frame they were handed over at, the
        #: event, and the edits to report once the engine has applied it.
        self._pending: list[tuple[int, tuple, CimEdits]] = []

    @property
    def sim(self):
        """The export, kept up to date: ``sim.model`` for TOPS, ``sim.ids`` row name -> mRID."""
        return self.live.sim

    def attach(self, send: Callable[[tuple], None]) -> None:
        """Steer the engine at the other end of ``send``, which runs ``sim.model`` as it is now."""
        self.runner = RemoteRunner(self.live, send)

    def receive(self, message: tuple) -> None:
        """What the engine sent: its state, each frame."""
        self.runner.receive(message)

    def changes(self) -> list[str]:
        """Follow what the graph changed since the last call; say what was done, one line each."""
        if not self.version.changed():
            return []
        refresh_expired(self.live.exporter.repo)
        return follow(self.live, self.runner)

    # -- commands -----------------------------------------------------------------------------

    def command(self, command: Command) -> list[DataModel]:
        """Apply ``command``; return what to announce now (a ``SimEvent``). ``CommandRefused`` when it
        does not apply: an object of another kind, or a switch already in that state."""
        try:
            return [self._apply(command)]
        except (KeyError, ValueError) as error:
            mrid = getattr(command, "mRID", None)
            if isinstance(error, KeyError) and mrid and self._in_dead_part(mrid):
                raise CommandRefused(
                    f"{mrid} is in a part of the grid the slack bus cannot reach, which the simulation leaves out: "
                    "reconnect a line or close a breaker that feeds it"
                ) from error
            raise CommandRefused(str(error).strip("'\"")) from error

    def _in_dead_part(self, mrid: str) -> bool:
        """Whether a terminal of ``mrid`` (or ``mrid``, a node) is in a de-energised part."""
        ids = self.sim.ids
        dead = ids.get("de_energised") or {}
        if not dead:
            return False
        if ids["node_to_bus"].get(mrid) in dead:
            return True
        try:
            found = self.live.exporter.repo.from_mRID(mrid)
        except (KeyError, ValueError):
            return False
        nodes = (getattr(getattr(t, "ConnectivityNode", None), "mRID", None) for t in getattr(found, "Terminals", None) or ())
        return any(ids["node_to_bus"].get(node) in dead for node in nodes)

    def reports(self) -> list[DataModel]:
        """What happened since the last call: what protection did (``SimEvent``), and what the
        simulation did that the graph should know, once the engine has applied it (``CimEdits``): the
        switches it operated, and the terminals of the lines it operated."""
        out: list[DataModel] = self._protect()
        for mrid, attribute, value, t in self.live.cim_changes():
            cause, request = self._causes.pop(mrid, ("command", None))
            out.append(self._edits(cause, request, t, [CimEdit(mRID=mrid, attribute=attribute, value=value)]))
        runner, waiting = self.runner, []
        rejected = [event for event, _ in runner.rejected]
        for sent, event, edits in self._pending:
            if runner.frame <= sent:
                waiting.append((sent, event, edits))
            elif event not in rejected:
                out.append(edits)
        self._pending = waiting
        return out

    def _apply(self, command: Command) -> SimEvent:
        live, ids, runner = self.live, self.sim.ids, self.runner
        mrid = getattr(command, "mRID", None)
        if isinstance(command, OperateSwitchCommand):
            changed = live.open(mrid) if command.open else live.close(mrid)
            if not changed:
                raise ValueError(f"{mrid} is already {'open' if command.open else 'closed'}")
            self._causes[mrid] = ("command", command.request_id)
            return self._event("open" if command.open else "close", command, "command")
        if isinstance(command, OperateLineCommand):  # a line or a transformer, by its terminal
            category, model, name = _branch(ids, mrid)
            action = "connect" if command.in_service else "disconnect"
            event = (category, model, name, action, {})
            runner.submit(*event[:4])
            edits = self._edits("command", command.request_id, live.time, self._terminals(mrid, command.in_service))
            self._pending.append((runner.frame, event, edits))
            return self._event("reconnect" if command.in_service else "trip", command, "command")
        if isinstance(command, TripBranchCommand | ReconnectBranchCommand):
            category, model, name = _branch(ids, mrid)
            runner.submit(category, model, name, "connect" if isinstance(command, ReconnectBranchCommand) else "disconnect")
            return self._event("reconnect" if isinstance(command, ReconnectBranchCommand) else "trip", command, "disturbance")
        if isinstance(command, ShortCircuitCommand | ClearShortCircuitCommand):
            bus = ids["node_to_bus"].get(mrid)
            if bus is None or bus in ids.get("de_energised", {}):
                raise ValueError(f"{mrid} is no energised node of the simulation")
            if isinstance(command, ShortCircuitCommand):
                runner.submit("buses", "", bus, "short_circuit", y=command.y)
                return self._event("short_circuit", command, "disturbance")
            runner.submit("buses", "", bus, "clear_short_circuit")
            return self._event("clear_short_circuit", command, "disturbance")
        if isinstance(command, LoadStepCommand):
            power = {key: value for key, value in (("P", command.p_mw), ("Q", command.q_mvar)) if value is not None}
            runner.submit("loads", "Load", _row(ids, "loads", mrid), "set_power", **power)
            return self._event("load_step", command, "disturbance", detail=", ".join(f"{k} {v:g}" for k, v in power.items()))
        if isinstance(command, FaultAndClearCommand):
            return self._fault(command)
        if isinstance(command, ResetSimulationCommand):
            said = restart(live, runner, "a reset")
            return self._event("reset", command, "command", detail="; ".join(said))
        raise ValueError(f"{command.name} is not a command of the simulation")

    # -- protection ---------------------------------------------------------------------------

    def _fault(self, command: FaultAndClearCommand) -> SimEvent:
        """A fault at one end of a line now; cleared after ``clear_ms`` by the breakers that isolate the
        line, or by the line itself where there are none: on time on the engine's clock, and here at
        the next look after, which reports the breakers opened."""
        live, ids, runner, line = self.live, self.sim.ids, self.runner, command.mRID
        _row(ids, "lines", line)
        terminal = next(
            (t for t in live.exporter.repo.from_mRID(line).Terminals if t.sequenceNumber == command.end), None
        )
        bus = ids["node_to_bus"].get(getattr(getattr(terminal, "ConnectivityNode", None), "mRID", None))
        if bus is None or bus in ids.get("de_energised", {}):
            raise ValueError(f"end {command.end} of {line} is on no energised bus of the simulation")
        runner.submit("buses", "", bus, "short_circuit", y=command.y)
        when = live.time + command.clear_ms / 1000.0
        breakers = self._isolating(line)
        switch = {mrid: name for name, mrid in ids.get("switches", {}).items()}
        opening = [("event", ("switches", "Switch", switch[b], "open", {})) for b in breakers if b in switch]
        if not opening:
            opening = [("event", ("lines", "Line", _row(ids, "lines", line), "disconnect", {}))]
        runner.at(when, [*opening, ("event", ("buses", "", bus, "clear_short_circuit", {}))])

        def cleared() -> list[DataModel]:
            runner.submit("buses", "", bus, "clear_short_circuit")  # the engine has: here, the shadow
            return self._trip(line, f"cleared the fault at end {command.end} after {command.clear_ms:g} ms", breakers)

        self._timers.append((when, cleared))
        return self._event(
            "short_circuit", command, "disturbance", detail=f"at end {command.end}, cleared after {command.clear_ms:g} ms"
        )

    def _protect(self) -> list[DataModel]:
        """What is due now: the timers whose time has come, and the overloads whose time is spent."""
        live, runner = self.live, self.runner
        if runner.build != self._built:  # a model built again: a grid at steady state
            self._built, self.limits, self._tripped = runner.build, self._limits(), set()
            self._overload.forget()
        out: list[DataModel] = []
        now = live.time + 1e-9
        due, self._timers = [a for t, a in self._timers if t <= now], [(t, a) for t, a in self._timers if t > now]
        for action in due:
            out += action()
        if not self.protection.enabled or not self.limits:
            return out
        readings = [
            (line, end, abs(live.current(line, end)), limit)
            for (line, end), limit in self.limits.items()
            if line not in self._tripped
        ]
        for line, end, ratio in self._overload.check(live.time, readings):
            if line not in self._tripped:  # both ends' relays may run out in one check: one trip
                out += self._trip(line, f"overload: {ratio:.2f} x its pickup current at end {end}")
        return out

    def _trip(self, line: str, why: str, breakers: list[str] | None = None) -> list[DataModel]:
        """Take ``line`` out as its protection does: by the breakers that isolate it, or by its terminal
        where there are none. The breakers and the terminal are reported as protection's."""
        live, runner = self.live, self.runner
        self._tripped.add(line)
        breakers = self._isolating(line) if breakers is None else breakers
        out: list[DataModel] = []
        opened = [b for b in breakers if b in self.sim.ids.get("switches", {}).values() and live.open(b)]
        for breaker in opened:
            self._causes[breaker] = ("protection", None)
            out.append(self._said("open", breaker, "protection", why))
        if not breakers:
            name = _row(self.sim.ids, "lines", line)
            event = ("lines", "Line", name, "disconnect", {})
            runner.submit(*event[:4])
            self._pending.append((runner.frame, event, self._edits("protection", None, live.time, self._terminals(line, False))))
        out.append(self._said("trip", line, "protection", why))
        return out

    def _isolating(self, line: str) -> list[str]:
        """The breakers that cut ``line`` off, at both ends."""
        return sorted({b for end in (1, 2) for b in self.live.breakers_isolating(line, end)})

    def _limits(self) -> dict[tuple[str, int], float]:
        """Each line end's permanent current limit, where the graph has one."""
        found = {}
        for mrid in self.sim.ids.get("lines", {}).values():
            for end in (1, 2):
                limit = self.live.limit(mrid, end)
                if limit is not None:
                    found[(mrid, end)] = float(limit)
        return found

    def _said(self, kind: str, mrid: str, cause: str, detail: str) -> SimEvent:
        return SimEvent(timestamp=utcnow(), mRID=mrid, kind=kind, cause=cause, sim_time=self.live.time, detail=detail)

    def _terminals(self, line: str, connected: bool) -> list[CimEdit]:
        """The edits that take a line out by its first terminal, or bring it back by all of them: as
        the graph's writer does it for a line with no breaker."""
        terminals = sorted(self.live.exporter.repo.from_mRID(line).Terminals, key=lambda t: t.sequenceNumber or 0)
        chosen = terminals if connected else terminals[:1]
        return [CimEdit(mRID=t.mRID, attribute="ACDCTerminal.connected", value=connected) for t in chosen]

    def _event(self, kind: str, command: Command, cause: str, *, detail: str | None = None) -> SimEvent:
        return SimEvent(
            timestamp=utcnow(),
            mRID=getattr(command, "mRID", None) or STREAM_ID,
            kind=kind,
            cause=cause,
            sim_time=self.live.time,
            detail=detail,
            request_id=command.request_id,
        )

    @staticmethod
    def _edits(cause: str, request: str | None, sim_time: float, edits: list[CimEdit]) -> CimEdits:
        return CimEdits(timestamp=utcnow(), producer=PRODUCER, cause=cause, sim_time=sim_time, request_id=request, edits=edits)


def _row(ids: dict[str, Any], component: str, mrid: str) -> str:
    """The model's row of ``mrid`` in ``component``; ``KeyError`` naming it when there is none."""
    for name, found in ids.get(component, {}).items():
        if found == mrid:
            return name
    raise KeyError(f"{mrid} is no {component[:-1]} of the simulation")


def _branch(ids: dict[str, Any], mrid: str) -> tuple[str, str, str]:
    """The TOPS category, model and row of a line or a transformer."""
    for component, category, model in (("lines", "lines", "Line"), ("transformers", "trafos", "Trafo")):
        for name, found in ids.get(component, {}).items():
            if found == mrid:
                return category, model, name
    raise KeyError(f"{mrid} is no line or transformer of the simulation")


def _watch(control, link, up, settings: CimSettings, poll: float, dt: float, protection: ProtectionSettings) -> None:
    """The controller's process: export, say so, then take the engine's state as it comes, look at the
    stamp every ``poll`` seconds, say what it reports, and apply each command that comes down
    ``control`` at once, until told to stop (``None`` on ``control``, or its end closing)."""
    try:
        version = GraphVersion(open_store(settings))  # watched from before the export
        repo = connect_reader(settings)
        controller = Controller(repo, version, dt=dt, protection=protection)
        controller.attach(link.send)
        up.send(("ready", controller.sim.model, controller.sim.ids, read_analogs(repo)))
    except Exception as error:  # noqa: BLE001 -- the caller raises it
        up.send(("error", error))
        return
    try:
        while True:
            started = time.monotonic()
            while link.poll():
                controller.receive(link.recv())
            try:
                said = controller.changes()
                for line in said:
                    up.send(("log", line))
                if any("built again" in line for line in said):
                    up.send(("ids", controller.sim.ids))
            except (BrokenPipeError, EOFError, OSError):
                raise
            except Exception as error:  # noqa: BLE001 -- a store down for a moment must not end the stream
                up.send(("warning", f"the graph could not be followed, the simulation keeps its last state: {error}"))
            if reports := controller.reports():
                up.send(("said", reports))
            while (wait := poll - (time.monotonic() - started)) > 0 and control.poll(wait):
                message = control.recv()
                if message is None:
                    return
                _answer(controller, message[1], up)
    except (BrokenPipeError, EOFError, OSError, KeyboardInterrupt):
        return


def _answer(controller: Controller, command: Command, up) -> None:
    """Apply ``command``, and say what came of it: ``("answer", request_id, messages, refusal)``."""
    try:
        messages = controller.command(command)
    except CommandRefused as refused:
        up.send(("answer", command.request_id, None, str(refused)))
        return
    except Exception as error:  # noqa: BLE001 -- said back, and the controller goes on
        up.send(("answer", command.request_id, None, f"{type(error).__name__}: {error}"))
        return
    up.send(("answer", command.request_id, messages, None))
    if isinstance(command, ResetSimulationCommand):
        up.send(("ids", controller.sim.ids))


class ControllerProcess:
    """A ``Controller`` of the graph ``settings`` names (a shared store: Oxigraph), in a process of its
    own: ``LiveTops`` and a look at the version stamp every ``poll`` seconds. It steers the engine's
    process through ``link`` (the engine's end of a duplex pipe, for ``EngineProcess``). ``ready``
    waits for the export; ``receive`` gives what the controller says, until it ends."""

    def __init__(
        self, settings: CimSettings, *, poll: float, dt: float, protection: ProtectionSettings | None = None
    ) -> None:
        context = multiprocessing.get_context("spawn")
        control_read, self._control = context.Pipe(duplex=False)
        #: The engine's end of the link, for the engine's process to take over.
        self.link, ours = context.Pipe()
        self._up, up_write = context.Pipe(duplex=False)
        self._process = context.Process(
            target=_watch,
            args=(control_read, ours, up_write, settings, poll, dt, protection or ProtectionSettings()),
            name="rtsim-follow",
            daemon=True,
        )
        self._process.start()
        for end in (control_read, ours, up_write):
            end.close()

    def ready(self) -> tuple:
        """Wait for the export (blocking: from a thread): its model, ids and the PMU Analogs. Raises what
        the controller could not get past."""
        message = self._receive()
        if message[0] != "ready":
            raise message[1] if message[0] == "error" else RuntimeError(f"the controller said {message!r}")
        return message[1:]

    def command(self, command: Command) -> None:
        """Hand ``command`` over; its answer comes back through ``receive``."""
        self._control.send(("command", command))

    def receive(self) -> tuple | None:
        """What the controller says next (blocking: from a thread): ``("log" | "warning", text)``,
        ``("said", reports)``, ``("answer", request_id, messages, refusal)`` or ``("ids", ids)``;
        ``None`` once it has ended."""
        message = self._receive()
        return None if message[0] == "gone" else message

    def _receive(self) -> tuple:
        try:
            return self._up.recv()
        except (EOFError, OSError):
            return ("gone", RuntimeError("the controller's process ended"))

    def close(self) -> None:
        try:
            self._control.send(None)
        except (BrokenPipeError, OSError):
            pass
        self._process.join(timeout=5)
        if self._process.is_alive():
            self._process.terminate()
        for end in (self._control, self._up):
            end.close()
