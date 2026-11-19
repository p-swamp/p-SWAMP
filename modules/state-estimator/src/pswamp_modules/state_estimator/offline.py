"""Run modules over the live grid simulation offline: no server, no transport, no Kafka.

The general part of a module's simulation example, so the example itself says only what is its own:
the grid, the events, the modules, and the plot.

    grid = Grid.load("grids/nordic44")            # or Grid.load() for LazyCIM's Nordic44
    trip = TripBranchCommand(mRID=grid.mrid("300SIMA-BLAFALLI", "ACLineSegment"))
    run = simulate(grid, [StateEstimatorModule()], seconds=10, events=[(4.0, trip)])
    t, results = run.results("state-estimator")

What it does, as a deployment would, in one process:

- **The grid** is an embedded Oxigraph store (pyoxigraph) of the script's own, given what p-SWAMP
  needs by ``prepare`` (machine dynamics, and PMU and SCADA Analogs where it has none). Every module
  with ``cim = True`` and the simulation read it, each through a repository of its own, so the
  Analog a frame column names is one the module finds in the graph.
- **The simulation** (``rtsim-from-cim``) is named by its entry point, never imported: a module, and
  its examples, import no other module. It runs in real time, so ``seconds`` of simulation take that
  long, plus the build.
- **Events** are the simulation's own commands (``pswamp_models.rtsim``), each sent when the frames
  reach its simulated time: an operation (``OperateSwitchCommand``) or a disturbance
  (``TripBranchCommand``, ``FaultAndClearCommand``, ``LoadStepCommand``, ...).
- **The graph follows the simulation**: the ``CimEdits`` it reports (a breaker an operation or its
  protection opened) are written to the store, as the server's CIM graph app does. A store with no
  version stamp is re-read every 2 s by its readers, so a module sees an edit within that.
- **Modules are fed by class**: every message (a frame, a module's result) goes to every module that
  reads its class, in the order given, so one module's results can feed the next.

Needs ``pswamp-core[oxigraph]`` and ``pswamp-rtsim-from-cim`` installed (an example extra): both are
imported only when used, so the module itself does not depend on them.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from pswamp_core.cim import prepare
from pswamp_core.modules import Module
from pswamp_core.scripts import source
from pswamp_core.util.time import utcnow
from pswamp_models.cim import CimEdits
from pswamp_models.common.command import Command
from pswamp_models.common.data_model import DataModel
from pswamp_models.pmu import PmuFrame
from pswamp_models.rtsim import SimEvent

__all__ = ["Grid", "Run", "simulate"]

#: Time to allow the simulation to build its model before the first frame, s.
BUILD_ALLOWANCE = 120.0


class Grid:
    """A CIM grid in an embedded Oxigraph store, ready for the simulation and the modules."""

    def __init__(self, store: Any) -> None:
        self.store = store
        #: How many measurements ``prepare`` added (0: the grid had its own).
        self.added = 0

    @classmethod
    def load(cls, folder: str | Path | None = None) -> Grid:
        """``folder``'s CGMES files (``*.xml``: EQ, SSH, TP, SV, ...), or LazyCIM's Nordic44 (downloaded
        once, into its cache), with the CGMES vocabularies, Dynamics and Operation included, one named
        graph per profile; then ``prepare``'d."""
        from lazycim import OxigraphBackend
        from lazycim.demo import cgmes_profile_files, nordic44_files

        files = sorted(Path(folder).glob("*.xml")) if folder is not None else nordic44_files()
        if not files:
            raise FileNotFoundError(f"no CGMES files (*.xml) in {folder}")
        store = OxigraphBackend("grid")
        store.load_cgmes(files, cgmes_profile_files(dynamics=True))
        grid = cls(store)
        grid.added = prepare(grid.repository())
        return grid

    def repository(self) -> Any:
        """A new LazyCIM repository over the store. One per reader: the simulation owns its own."""
        from lazycim import CIMRepository
        from lazycim.demo import CIM100

        return CIMRepository(self.store, default_namespace=CIM100, graphs="discover")

    def mrid(self, name: str, cim_class: str | None = None) -> str:
        """The mRID of the object called ``name`` (of ``cim_class``, e.g. ``"ACLineSegment"``, when given).
        ``LookupError`` unless exactly one matches."""
        from lazycim.demo import CIM100

        of_class = f"?s a <{CIM100}{cim_class}> ." if cim_class else ""
        query = f"""
            SELECT DISTINCT ?mrid WHERE {{ GRAPH ?g {{ ?s <{CIM100}IdentifiedObject.name> ?name . }}
                                          GRAPH ?h {{ ?s <{CIM100}IdentifiedObject.mRID> ?mrid . }}
                                          {"GRAPH ?k { " + of_class + " }" if of_class else ""}
                                          FILTER (str(?name) = {_literal(name)}) }}"""
        found = [row["mrid"]["value"] for row in self.store.execute(query)["results"]["bindings"]]
        if len(found) != 1:
            hint = "; name its class" if len(found) > 1 and not cim_class else ""
            raise LookupError(f"{len(found)} {cim_class or 'object'}s are called {name!r}{hint}")
        return found[0]

    def apply(self, edits: CimEdits) -> None:
        """Write what the simulation reports, all of it in one update (the server's writer, minus its
        allow-list), through ``pswamp_core.cim.testing``: the graph has one writer per store."""
        from pswamp_core.cim.testing import apply

        apply(self.repository(), edits)


def _literal(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


@dataclass
class Run:
    """What a ``simulate`` produced, each message with its simulated time (s from the first frame)."""

    t: list[float] = field(default_factory=list)  #: per frame
    frames: list[PmuFrame] = field(default_factory=list)
    #: What each module published, by its ``name``: (t, message).
    published: dict[str, list[tuple[float, DataModel]]] = field(default_factory=dict)
    #: What the simulation announced (disturbances, protection): (t, event).
    events: list[tuple[float, SimEvent]] = field(default_factory=list)
    #: What it reported to the graph (and was written there): (t, edits).
    edits: list[tuple[float, CimEdits]] = field(default_factory=list)

    def results(self, module: str | Module) -> tuple[list[float], list[Any]]:
        """A module's results: their times, and their bodies (``.result``)."""
        name = module if isinstance(module, str) else module.name
        found = [(t, m) for t, m in self.published.get(name, []) if hasattr(m, "result")]
        return [t for t, _ in found], [m.result for _, m in found]


def simulate(
    grid: Grid,
    modules: Sequence[Module],
    seconds: float,
    events: Iterable[tuple[float, Command]] = (),
    *,
    verbose: bool = True,
    **settings: Any,
) -> Run:
    """Simulate ``grid`` for ``seconds`` (simulated, which is real time), feeding ``modules``, sending
    each event's command when the frames reach its time. ``settings`` go to the simulation
    (``RTSIM_*`` by their lower-case names: ``protection="off"``, ``scada_period=2``, ...; no SCADA
    scans unless asked). A synchronous call: it runs its own event loop."""
    settings.setdefault("scada_period", 0)
    return asyncio.run(_simulate(grid, list(modules), seconds, sorted(events, key=lambda e: e[0]), verbose, settings))


async def _simulate(grid, modules, seconds, events, verbose, settings) -> Run:
    say = print if verbose else (lambda *_: None)
    sim = source("rtsim-from-cim", repo=grid.repository(), **settings)
    for module in modules:
        if module.cim and module._cim_repo is None:
            module.cim_repo = grid.repository()  # the grid of the frames, not the environment's
        await module.setup()
    run, pending = Run(published={m.name: [] for m in modules}), list(events)
    first = None
    say("building the simulation ...")
    try:
        async for message in sim.aread(end=utcnow() + timedelta(seconds=seconds + BUILD_ALLOWANCE)):
            if isinstance(message, PmuFrame):
                first = first or message.timestamp
                t = (message.timestamp - first).total_seconds()
                if t >= seconds:
                    break
                while pending and pending[0][0] <= t:
                    _, command = pending.pop(0)
                    say(f"t={t:5.2f} s: sending {command.name} {getattr(command, 'mRID', '')}")
                    for answer in await sim.arun_command(command):
                        await _said(answer, t, grid, run, say)
                run.t.append(t)
                run.frames.append(message)
                await _feed(message, t, modules, run)
            else:
                t = run.t[-1] if run.t else 0.0
                await _said(message, t, grid, run, say)
                await _feed(message, t, modules, run)
    finally:
        for module in modules:
            await module.teardown()
    say(f"{len(run.frames)} frames, {len(run.events)} events, {len(run.edits)} edits to the graph")
    return run


async def _said(message: DataModel, t: float, grid: Grid, run: Run, say) -> None:
    """What the simulation says beside its frames: an event to keep, edits to write to the graph."""
    if isinstance(message, SimEvent):
        run.events.append((t, message))
        say(f"t={t:5.2f} s: {message.kind} {message.mRID} ({message.cause}){': ' + message.detail if message.detail else ''}")
    elif isinstance(message, CimEdits):
        grid.apply(message)
        run.edits.append((t, message))


def _reads(module: Module) -> tuple[type, ...]:
    inputs = module.inputs
    return tuple(inputs.values()) if isinstance(inputs, dict) else tuple(inputs)


async def _feed(message: DataModel, t: float, modules: list[Module], run: Run) -> None:
    """``message`` to every module that reads its class, and what they publish on to the others."""
    queue = [message]
    while queue:
        current = queue.pop(0)
        for module in modules:
            if isinstance(current, _reads(module)):
                out = await module.arun(current)
                run.published[module.name].extend((t, m) for m in out)
                queue.extend(out)
