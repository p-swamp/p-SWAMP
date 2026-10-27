"""The grid the monitor draws, read from the CIM graph: the same grid the simulation runs.

A **bus is a station of the live stream**: one per voltage level of each substation, named as the
simulation names its PMUs (``<substation>_<kV>``, ``Beta_400``; ``rtsim_from_cim.pmu``), so the
islanding detector's stations, the phasors and the frequencies are the buses' own names. A bus
stands where the graph's GL profile places its substation; a substation's lower voltage levels are
drawn a little beside it, so that each can be coloured on its own.

A **branch** is a line or a transformer whose ends are in two stations: a line runs along its GL
route, a transformer straight across (between two voltage levels of one substation, that is a short
stub). A branch is named by its CIM name, whitespace as ``_``, as the simulation names the channel of
its current (``I_<line>``); a second branch of one name gets its mRID added.

The country outlines are a fixture (``data/nordic_outlines.json``, the Nordic coastlines and borders
the Qt grid view draws), drawn when every bus lies inside them.

Read once, through a reader of the graph's own (``connect_reader``, which waits for the CIM graph app
to load the grid), on one thread: it is a few dozen queries.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from lazycim import F, L
from lazycim.sim.base import Tables
from lazycim.sim.topology import terminal_table

from pswamp_core.cim import connect_reader, measurement_table, station_name
from pswamp_web.wire import GridBranch, GridBus, GridDiagram, GridModel, PmuSite

OUTLINES_PATH = Path(__file__).parent / "data" / "nordic_outlines.json"

#: Padding around the outermost buses, as a fraction of the bounding box.
BBOX_MARGIN = 0.06
#: How far a substation's lower voltage levels are drawn from it, as a fraction of the grid's extent.
LEVEL_OFFSET = 0.012


@dataclass(frozen=True)
class Topology:
    model: GridModel
    #: A current's Analogs (mRIDs: its magnitude's and its angle's) to the branch it measures, by the
    #: branch's name in ``model``.
    branch_of_analog: dict[str, str]


def _text(value) -> str:
    return str(value).strip() if isinstance(value, str) else ""


def _number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def read_topology(repo=None) -> Topology:
    """The grid in the CIM graph (``repo``, or a reader of the process's store), as the monitor draws it."""
    repo = repo or connect_reader()
    tables = Tables(repo)
    terminals = terminal_table(tables)
    nodes = tables.query(L.ConnectivityNodes).to_dataframe(
        node=F.mRID,
        substation=F.ConnectivityNodeContainer.Substation.mRID,
        name=F.ConnectivityNodeContainer.Substation.name,
        kv=F.ConnectivityNodeContainer.BaseVoltage.nominalVoltage,
    )
    points = tables.query(L.PositionPoints).to_dataframe(loc=F.Location.mRID, x=F.xPosition, y=F.yPosition, seq=F.sequenceNumber)
    placed = tables.query(L.Locations).to_dataframe(loc=F.mRID, psr=F.PowerSystemResources.mRID)

    route: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for row in points.sort_values("seq").itertuples():
        x, y = _number(row.x), _number(row.y)
        if x is not None and y is not None:
            route[row.loc].append((x, y))
    where = {psr: route.get(loc, []) for loc, psr in zip(placed["loc"], placed["psr"], strict=True)}

    # The stations: one per voltage level of a placed substation.
    station_of_node: dict[str, str] = {}
    levels: dict[str, dict[str, float]] = defaultdict(dict)  # substation -> station -> kV
    substation_name: dict[str, str] = {}
    for row in nodes.itertuples():
        kv = _number(row.kv)
        if not isinstance(row.substation, str) or kv is None or not where.get(row.substation):
            continue
        station = station_name(_text(row.name) or row.substation, kv)
        station_of_node[row.node] = station
        levels[row.substation][station] = kv
        substation_name[row.substation] = _text(row.name) or row.substation

    anchors = {substation: where[substation][0] for substation in levels}
    lons = [lon for lon, _ in anchors.values()] or [0.0]
    lats = [lat for _, lat in anchors.values()] or [0.0]
    aspect = 1 / max(math.cos(math.radians((min(lats) + max(lats)) / 2)), 0.1)
    radius = LEVEL_OFFSET * max(max(lons) - min(lons), (max(lats) - min(lats)) * aspect, 0.5)

    position: dict[str, tuple[float, float]] = {}
    buses: list[GridBus] = []
    for substation, stations in sorted(levels.items(), key=lambda item: substation_name[item[0]]):
        lon, lat = anchors[substation]
        ordered = sorted(stations, key=lambda station: -stations[station])  # the highest voltage at the substation
        for i, station in enumerate(ordered):
            angle = 2 * math.pi * (i - 1) / max(len(ordered) - 1, 1) - math.pi / 2
            at = (lon, lat) if i == 0 else (lon + radius * math.cos(angle), lat + radius * math.sin(angle) / aspect)
            position[station] = at
            buses.append(
                GridBus(name=station, v_nom=stations[station], area=substation_name[substation], lon=at[0], lat=at[1])
            )

    # The branches: a line or a transformer between two stations.
    stations_of: dict[str, list[str]] = defaultdict(list)
    for row in terminals.sort_values("sequence").itertuples():
        station = station_of_node.get(row.node)
        if station is not None and station not in stations_of[row.equipment]:
            stations_of[row.equipment].append(station)
    branches: list[GridBranch] = []
    paths: dict[str, list[tuple[float, float]]] = {}
    name_of: dict[str, str] = {}
    for kind, query in (("line", L.ACLineSegments), ("trafo", L.PowerTransformers)):
        table = tables.query(query).to_dataframe(mRID=F.mRID, name=F.name)
        for mrid, raw in sorted(zip(table["mRID"], table["name"], strict=True), key=lambda item: (_text(item[1]), item[0])):
            ends = stations_of.get(mrid, [])
            if len(ends) < 2:
                continue  # one end not placed, or both in one voltage level
            name = _part(_text(raw) or mrid)
            if name in paths:
                name = f"{name}_{mrid}"
            name_of[mrid] = name
            start, end = position[ends[0]], position[ends[1]]
            paths[name] = _path(start, end, where.get(mrid, []) if kind == "line" else [])
            branches.append(GridBranch(name=name, from_bus=ends[0], to_bus=ends[1], kind=kind))
            for other in ends[2:]:  # a three-winding transformer: its other windings from the first
                paths[f"{name}_{other}"] = [start, position[other]]
                branches.append(GridBranch(name=f"{name}_{other}", from_bus=ends[0], to_bus=other, kind=kind))

    branch_of_analog = {}
    for row in measurement_table(repo).itertuples():
        if row.source != "PMU" or row.quantity not in ("I", "I_angle"):
            continue
        equipment = row.terminal_equipment if isinstance(row.terminal_equipment, str) else row.equipment
        if equipment in name_of:
            branch_of_analog[row.mRID] = name_of[equipment]

    xs = [lon for lon, _ in position.values()] or [0.0]
    ys = [lat for _, lat in position.values()] or [0.0]
    pad_x, pad_y = (max(xs) - min(xs)) * BBOX_MARGIN, (max(ys) - min(ys)) * BBOX_MARGIN
    bbox = (min(xs) - pad_x, min(ys) - pad_y, max(xs) + pad_x, max(ys) + pad_y)
    countries, outlines = _outlines((min(xs), min(ys), max(xs), max(ys)))
    diagram = GridDiagram(
        sld="cim",
        countries=countries,
        aspect_ratio=aspect,
        buses=position,
        branches=paths,
        outlines=outlines,
    )
    model = GridModel(
        buses=buses,
        branches=branches,
        pmus=[PmuSite(name=bus.name, lon=bus.lon, lat=bus.lat) for bus in buses],
        bbox=bbox,
        diagram=diagram,
    )
    return Topology(model=model, branch_of_analog=branch_of_analog)


def _path(start, end, route: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """From ``start`` to ``end`` along ``route``, which the GL profile may give either way round."""
    if route and math.dist(route[0], end) < math.dist(route[0], start):
        route = route[::-1]
    inner = [point for point in route if point != start and point != end]
    return [start, *inner, end]


def _outlines(extent) -> tuple[list[str], list[list[tuple[float, float]]]]:
    """The fixture's countries and outlines when every bus (``extent``: lon/lat min, then max) lies inside
    them; none otherwise. The buses, not the padded bounding box: a grid that fills the Nordic
    countries, as Nordic44 does, reaches their edges."""
    fixture = json.loads(OUTLINES_PATH.read_text())
    points = [point for ring in fixture["outlines"] for point in ring]
    lon_min, lat_min = min(p[0] for p in points), min(p[1] for p in points)
    lon_max, lat_max = max(p[0] for p in points), max(p[1] for p in points)
    inside = lon_min <= extent[0] and lat_min <= extent[1] and extent[2] <= lon_max and extent[3] <= lat_max
    if not inside:
        return [], []
    return fixture["countries"], [[tuple(point) for point in ring] for ring in fixture["outlines"]]


def _part(text: object) -> str:
    """``text`` as a branch's name, as the simulation names its channel (``I_<branch>``): whitespace runs as ``_``."""
    return re.sub(r"\s+", "_", str(text).strip())
