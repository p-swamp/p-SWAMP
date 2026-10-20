"""The CIM graph as this app sees it: the one writer of the graph, what it says is switched off, and
where it all is on the map.

**This is the only code that writes the CIM graph** (``Writer``). The store (``pswamp_core.cim``) is
filled by it when the server starts, and edited by it when a visitor operates the grid; every other
process and module only reads it. So the state the page shows changes only when this writes, and the
writer's own repository, which nothing else changes behind its back, is always right: it is read
after each write, from its cache, and pushed.

A switch is operated as it is. A line is taken out by the breakers of the bay at one of its ends
(``_bays``: from the end, across closed disconnectors, up to the first breakers, when nothing but the
line is in between), or, for a line with no such bay at either end, by disconnecting a terminal;
brought back by closing those breakers and connecting its terminals. Everything here is synchronous and slow (HTTP, or rdflib), and
runs on the app's one thread.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from lazycim import CIMRepository, F, L
from lazycim.demo import CIM100
from lazycim.sim.base import Tables
from lazycim.sim.topology import connectivity_buses, switch_states, terminal_table
from pswamp_core.cim import CimSettings, Store, open_store
from pswamp_core.cim.grid import NAMESPACE_ALIASES

from .model import CimLayout, LayoutBranch, LayoutBreaker, LayoutSubstation, Point

__all__ = ["GridState", "Writer", "read_layout", "read_state"]


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

    def state(self) -> GridState:
        self.tables.refresh()
        return read_state(self.tables)

    def set_switch(self, mrid: str, open: bool) -> list[str]:  # noqa: A002
        """Open or close the switch ``mrid``: one update. ``LookupError`` when there is none."""
        try:
            switch = self.repo.from_mRID(mrid)
        except ValueError:
            switch = None
        if switch is None or not hasattr(switch, "open"):
            raise LookupError(f"no switch {mrid}")
        switch.open = open
        self.repo.commit()
        return [f"{mrid} {'opened' if open else 'closed'}"]

    def set_line(self, mrid: str, open: bool) -> list[str]:  # noqa: A002
        """Take the line ``mrid`` out (``open``) or bring it back: one update (see the module)."""
        tables = Tables(self.repo)
        ends = _bays(tables, mrid)
        if not ends:
            raise LookupError(f"no line {mrid}")
        done: list[str] = []
        if open:
            breakers = next((found for found in ends if found), [])
            for breaker in breakers:
                self.repo.from_mRID(breaker).open = True
                done.append(f"{breaker} opened")
            if not breakers:
                terminals = terminal_table(tables)
                terminal = sorted(terminals[terminals["equipment"] == mrid].itertuples(), key=lambda t: t.sequence)[0]
                self.repo.from_mRID(terminal.terminal).connected = False
                done.append(f"terminal {terminal.terminal} disconnected")
        else:
            for breaker in sorted({b for found in ends for b in found}):
                self.repo.from_mRID(breaker).open = False
                done.append(f"{breaker} closed")
            terminals = terminal_table(tables)
            for terminal in terminals[terminals["equipment"] == mrid]["terminal"]:
                self.repo.from_mRID(terminal).connected = True
        self.repo.commit()
        return done

    def reset(self) -> None:
        """Put the steady-state hypothesis back as it was loaded, in one update."""
        self.store.reset()
        self.repo.expire(profile="SSH")


def _text(value) -> str:
    return str(value or "").strip()


def read_layout(repo) -> CimLayout:
    """The substations that have a position (the GL profile: ``xPosition`` is the longitude and
    ``yPosition`` the latitude), the lines and transformers between them, and the breakers in them.
    Each line says the one breaker that takes it out on its own, if it has one."""
    tables = Tables(repo)
    terminals = terminal_table(tables)
    points = tables.query(L.PositionPoints).to_dataframe(loc=F.Location.mRID, x=F.xPosition, y=F.yPosition, seq=F.sequenceNumber)
    placed = tables.query(L.Locations).to_dataframe(loc=F.mRID, psr=F.PowerSystemResources.mRID)
    nodes = tables.query(L.ConnectivityNodes).to_dataframe(node=F.mRID, substation=F.ConnectivityNodeContainer.Substation.mRID)
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

    positioned: dict[str, LayoutSubstation] = {}
    for mrid, name in zip(names["mRID"], names["name"], strict=True):
        points_of = route.get(where.get(mrid, ""), [])
        if points_of:
            lon, lat = points_of[0]
            positioned[mrid] = LayoutSubstation(mrid=mrid, name=_text(name) or mrid, position=Point(lon=lon, lat=lat))

    branches: list[LayoutBranch] = []
    for kind, table in (("line", lines), ("transformer", trafos)):
        for mrid, name in zip(table["mRID"], table["name"], strict=True):
            ends = substations_at.get(mrid, [])
            if len(ends) != 2 or not all(end in positioned for end in ends):
                continue  # inside one substation, or not placed: nothing to draw
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
    return CimLayout(substations=list(positioned.values()), branches=branches, breakers=placed_breakers)
