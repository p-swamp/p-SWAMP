"""The CIM graph as this app sees it: the one writer of the graph, what it says is switched off, and
where it all is on the map.

**This is the only code that writes the CIM graph** (``Writer``). The store (``pswamp_core.cim``) is
filled by it when the server starts, and edited by it when a producer reports what the graph should
now hold (``apply``: the live simulation's ``CimEdits``, ADR-015), for the properties ``ALLOWED``
that producer; it also keeps the latest SCADA values, in a graph of their own that does not move the
version stamp (``write_scan``, ADR-016). Every other process and module only reads it. So the state the page shows changes only when this writes, and the
writer's own repository, which nothing else changes behind its back, is always right: it is read
after each write, from its cache, and pushed.

The layout says, for each line, the one breaker that operates it (``_bays``: from an end, across
closed disconnectors, up to the first breakers, when nothing but the line is in between); a line
with none is operated by its terminal. Operating it is the simulation's (ADR-015), which reports
what it did for ``apply`` to write. Everything here is synchronous and slow (HTTP, or rdflib), and
runs on the app's one thread.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass

from lazycim import CIMRepository, F, L
from lazycim.demo import CIM100
from lazycim.sim.base import Tables
from lazycim.sim.topology import connectivity_buses, switch_states, terminal_table
from pswamp_core.cim import CimSettings, Store, open_store
from pswamp_core.cim.grid import NAMESPACE_ALIASES, model_graph
from pswamp_models.cim import CimEdits
from pswamp_models.scada import ScadaScan
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF

from .model import CimLayout, LayoutBranch, LayoutBreaker, LayoutLoad, LayoutNode, LayoutSubstation, Point

__all__ = ["ALLOWED", "GridState", "Writer", "read_layout", "read_state"]

#: What each producer may have written, as ``<Class>.<attribute>``: the simulation, the state of the
#: switches it operated and of the terminals of the lines it operated.
ALLOWED: dict[str, frozenset[str]] = {"rtsim": frozenset({"Switch.open", "ACDCTerminal.connected"})}

CIM = Namespace(CIM100)
#: Where the mRID of a measurement's latest value is derived from: the same object at every scan.
_VALUES = uuid.UUID("0b9a1c55-3f0e-4c1d-9d0a-7363616461a0")


@dataclass(frozen=True)
class GridState:
    #: Every switch (mRID) and whether it is open now.
    switches: dict[str, bool]
    #: The lines and transformers (mRIDs) out of service now.
    out_of_service: frozenset[str]
    #: Every line and transformer (mRID).
    branches: frozenset[str]


def read_state(tables: Tables) -> GridState:
    """The switches, and the branches out of service: one of their terminals is disconnected, or a
    switch cuts an end off (the end's bus, through the switches that conduct, holds nothing else).
    ``tables`` is a repository's ``Tables``: one read per table, shared by the helpers below."""
    terminals = terminal_table(tables)
    switches = switch_states(tables)
    bus = connectivity_buses(tables, terminals)
    branches = {
        mrid
        for kind in (L.ACLineSegments, L.PowerTransformers)
        for mrid in tables.query(kind).to_dataframe(mRID=F.mRID).get("mRID", ())
    }
    connected = terminals[terminals["connected"] != False]  # noqa: E712 -- None is connected
    attached: dict[str, set[str]] = defaultdict(set)
    for node, equipment in zip(connected["node"], connected["equipment"], strict=True):
        if equipment not in switches:
            attached[bus[node]].add(equipment)
    out = {
        row.equipment
        for row in terminals.itertuples()
        if row.equipment in branches and (row.connected is False or attached[bus[row.node]] == {row.equipment})
    }
    return GridState(switches, frozenset(out), frozenset(branches))


def _bays(tables, mrid: str) -> list[list[str]]:
    """The breakers of the bay at each end of ``mrid``, end by end: from the end's node, across the
    closed switches that are not breakers, the breakers met on the way, opening which cuts the end
    off. Empty for an end where something else than the line is met first (a busbar, a generator):
    opening breakers there would take that out too."""
    terminals = terminal_table(tables)
    breakers = set(tables.query(L.Breakers).to_dataframe(mRID=F.mRID).get("mRID", ()))
    states = switch_states(tables)
    at: dict[str, list[tuple[str, str]]] = defaultdict(list)  # node -> (equipment, terminal)
    for row in terminals.itertuples():
        at[row.node].append((row.equipment, row.terminal))
    ends_of: dict[str, list[str]] = defaultdict(list)  # switch -> its nodes
    for row in terminals.itertuples():
        if row.equipment in states:
            ends_of[row.equipment].append(row.node)
    bays = []
    for end in terminals[terminals["equipment"] == mrid].sort_values("sequence").itertuples():
        reached, todo, found, alone = {end.node}, [end.node], set(), True
        while todo and alone:
            for equipment, _ in at[todo.pop()]:
                if equipment == mrid:
                    continue
                if equipment in breakers:
                    found.add(equipment)
                elif equipment in states and not states[equipment]:
                    for node in ends_of[equipment]:
                        if node not in reached:
                            reached.add(node)
                            todo.append(node)
                elif equipment not in states:
                    alone = False  # a busbar, a generator, another line: not this line's bay
        bays.append(sorted(found) if alone else [])
    return bays


def _operating_breaker(ends: list[list[str]]) -> str | None:
    """The one breaker that takes a line out on its own: the first end whose bay has exactly one."""
    return next((found[0] for found in ends if len(found) == 1), None)


class Writer:
    """The one writer of the CIM graph: it fills the store, and edits it. For one thread."""

    def __init__(self, settings: CimSettings | None = None) -> None:
        self.store: Store = open_store(settings)
        self.store.fill()
        self.writable = self.store.grid.writable
        self.repo = CIMRepository(
            self.store.writer_backend(),  # every commit also moves the version stamp
            default_namespace=CIM100,
            graphs=self.store.layout if self.writable else "discover",
            namespace_aliases=NAMESPACE_ALIASES,
        )
        #: The tables the state is read from, kept: refreshed from the repository's own cache, which its
        #: edits keep right, they cost no query after the first read.
        self.tables = Tables(self.repo)
        #: The grid's SCADA measurements and their source, once read (``_scada``).
        self._measured: dict[str, tuple[URIRef, str]] | None = None
        self._source: URIRef | None = None

    def state(self) -> GridState:
        self.tables.refresh()
        return read_state(self.tables)

    def apply(self, edits: CimEdits) -> list[str]:
        """Write what a producer reports (ADR-015), all or nothing, in one update. ``PermissionError``
        for a producer, or a property, not in ``ALLOWED``; ``LookupError`` for an object that does not
        have the property."""
        allowed = ALLOWED.get(edits.producer)
        if allowed is None:
            raise PermissionError(f"{edits.producer} may not write the CIM graph")
        refused = sorted({edit.attribute for edit in edits.edits} - allowed)
        if refused:
            raise PermissionError(f"{edits.producer} may not write {', '.join(refused)}")
        targets = []
        for edit in edits.edits:
            try:
                target = self.repo.from_mRID(edit.mRID)
            except ValueError:
                target = None
            prop = edit.attribute.partition(".")[2]
            if target is None or not hasattr(target, prop):
                raise LookupError(f"{edit.mRID} has no {edit.attribute}")
            targets.append((target, prop, edit))
        for target, prop, edit in targets:
            setattr(target, prop, edit.value)
        self.repo.commit()
        return [f"{edit.mRID} {edit.attribute} = {edit.value}" for _, _, edit in targets]

    def reset(self) -> None:
        """Put the steady-state hypothesis back as it was loaded, and forget the latest SCADA values, in
        one update."""
        self.store.reset()
        self.repo.expire(profile="SSH")

    def write_scan(self, scan: ScadaScan) -> tuple[int, int]:
        """Write a SCADA scan's values as the latest (ADR-016): one ``AnalogValue`` or ``DiscreteValue``
        per measurement, from the ``SCADA`` source, stamped with the scan's time, in the store's graph of
        latest values (``urn:pswamp:measurements``), which it replaces whole, in one update. The version
        stamp does not move, so no reader of the grid reads it again for a measurement. A value for a
        measurement that is not one of the grid's SCADA ones is left out. How many were written and left
        out."""
        measured, source = self._scada()
        graph, left_out = Graph(), 0
        at = Literal(scan.timestamp) if scan.timestamp is not None else None
        for kind, readings in (("Analog", scan.analogs), ("Discrete", scan.discretes)):
            for reading in readings:
                found = measured.get(reading.mRID)
                if found is None or found[1] != kind or source is None:
                    left_out += 1
                    continue
                mrid = str(uuid.uuid5(_VALUES, reading.mRID))
                value = URIRef(f"urn:uuid:{mrid}")
                graph.add((value, RDF.type, CIM[f"{kind}Value"]))
                graph.add((value, CIM["IdentifiedObject.mRID"], Literal(mrid)))
                graph.add((value, CIM[f"{kind}Value.{kind}"], found[0]))
                graph.add((value, CIM[f"{kind}Value.value"], Literal(reading.value)))
                graph.add((value, CIM["MeasurementValue.MeasurementValueSource"], source))
                if at is not None:
                    graph.add((value, CIM["MeasurementValue.timeStamp"], at))
        self.store.put_measurements(graph)
        return len(scan.analogs) + len(scan.discretes) - left_out, left_out

    def _scada(self) -> tuple[dict[str, tuple[URIRef, str]], URIRef | None]:
        """The grid's SCADA measurements, mRID to (IRI, ``Analog`` or ``Discrete``), and the SCADA source:
        read once, from the Operation profile, which nothing edits."""
        if self._measured is None:
            op = model_graph("OP")
            found = self.store.backend.execute(
                f"SELECT ?m ?id ?kind ?source WHERE {{ GRAPH <{op}> {{ "
                f"?source <{CIM}IdentifiedObject.name> \"SCADA\" . "
                f"?value <{CIM}MeasurementValue.MeasurementValueSource> ?source . "
                f"{{ ?value <{CIM}AnalogValue.Analog> ?m . BIND(\"Analog\" AS ?kind) }} UNION "
                f"{{ ?value <{CIM}DiscreteValue.Discrete> ?m . BIND(\"Discrete\" AS ?kind) }} "
                f"?m <{CIM}IdentifiedObject.mRID> ?id }} }}"
            )["results"]["bindings"]
            self._measured = {row["id"]["value"]: (URIRef(row["m"]["value"]), row["kind"]["value"]) for row in found}
            self._source = URIRef(found[0]["source"]["value"]) if found else None
        return self._measured, self._source


def _text(value) -> str:
    return str(value or "").strip()


def _number(value) -> float | None:
    """A float, or None for a value the graph does not give (None, NaN)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number


def read_layout(repo) -> CimLayout:
    """The substations that have a position (the GL profile: ``xPosition`` is the longitude and
    ``yPosition`` the latitude), with their connectivity nodes, the lines and transformers between
    them, and the breakers and loads in them. Each line says the one breaker that takes it out on its
    own, if it has one."""
    tables = Tables(repo)
    terminals = terminal_table(tables)
    points = tables.query(L.PositionPoints).to_dataframe(loc=F.Location.mRID, x=F.xPosition, y=F.yPosition, seq=F.sequenceNumber)
    placed = tables.query(L.Locations).to_dataframe(loc=F.mRID, psr=F.PowerSystemResources.mRID)
    nodes = tables.query(L.ConnectivityNodes).to_dataframe(
        node=F.mRID,
        name=F.name,
        kv=F.ConnectivityNodeContainer.BaseVoltage.nominalVoltage,
        substation=F.ConnectivityNodeContainer.Substation.mRID,
    )
    loads = tables.query(L.EnergyConsumers).to_dataframe(mRID=F.mRID, name=F.name, p=F.p, q=F.q)
    names = tables.query(L.Substations).to_dataframe(mRID=F.mRID, name=F.name)
    lines = tables.query(L.ACLineSegments).to_dataframe(mRID=F.mRID, name=F.name)
    trafos = tables.query(L.PowerTransformers).to_dataframe(mRID=F.mRID, name=F.name)
    breakers = tables.query(L.Breakers).to_dataframe(mRID=F.mRID, name=F.name)

    route: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for row in points.sort_values("seq").itertuples():
        route[row.loc].append((float(row.x), float(row.y)))
    where = {psr: loc for loc, psr in zip(placed["loc"], placed["psr"], strict=True)}
    substation_of = dict(zip(nodes["node"], nodes["substation"], strict=True))
    substations_at: dict[str, list[str]] = defaultdict(list)  # equipment -> substations of its terminals, in order
    for row in terminals.sort_values("sequence").itertuples():
        substation = substation_of.get(row.node)
        if isinstance(substation, str) and substation not in substations_at[row.equipment]:
            substations_at[row.equipment].append(substation)

    nodes_in: dict[str, list[LayoutNode]] = defaultdict(list)
    for row in nodes.itertuples():
        if isinstance(row.substation, str):
            nodes_in[row.substation].append(LayoutNode(mrid=row.node, name=_text(row.name) or row.node, nominal_kv=_number(row.kv)))
    positioned: dict[str, LayoutSubstation] = {}
    for mrid, name in zip(names["mRID"], names["name"], strict=True):
        points_of = route.get(where.get(mrid, ""), [])
        if points_of:
            lon, lat = points_of[0]
            in_it = sorted(nodes_in[mrid], key=lambda node: (-(node.nominal_kv or 0.0), node.name))
            positioned[mrid] = LayoutSubstation(mrid=mrid, name=_text(name) or mrid, position=Point(lon=lon, lat=lat), nodes=in_it)

    branches: list[LayoutBranch] = []
    for kind, table in (("line", lines), ("transformer", trafos)):
        for mrid, name in zip(table["mRID"], table["name"], strict=True):
            ends = substations_at.get(mrid, [])
            if kind == "transformer" and len(ends) == 1:
                ends = [ends[0], ends[0]]  # inside one substation (a 400/132 kV step): drawn there
            if len(ends) != 2 or not all(end in positioned for end in ends):
                continue  # a line inside one substation, or not placed: nothing to draw
            path = [Point(lon=lon, lat=lat) for lon, lat in route.get(where.get(mrid, ""), ())]
            branches.append(
                LayoutBranch(
                    mrid=mrid,
                    name=_text(name) or mrid,
                    kind=kind,
                    from_substation=ends[0],
                    to_substation=ends[1],
                    path=path,
                    breaker=_operating_breaker(_bays(tables, mrid)),
                )
            )

    placed_breakers = [
        LayoutBreaker(mrid=mrid, name=_text(name) or mrid, substation=substations_at[mrid][0])
        for mrid, name in zip(breakers["mRID"], breakers["name"], strict=True)
        if substations_at.get(mrid) and substations_at[mrid][0] in positioned
    ]
    placed_loads = [
        LayoutLoad(
            mrid=row.mRID,
            name=_text(row.name) or row.mRID,
            substation=substations_at[row.mRID][0],
            p_mw=_number(row.p),
            q_mvar=_number(row.q),
        )
        for row in loads.itertuples()
        if substations_at.get(row.mRID) and substations_at[row.mRID][0] in positioned
    ]
    return CimLayout(substations=list(positioned.values()), branches=branches, breakers=placed_breakers, loads=placed_loads)
