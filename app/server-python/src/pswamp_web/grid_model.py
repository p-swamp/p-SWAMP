# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The static grid topology, as the browser needs it.

Read once from the Nordic 44 database that ships inside the pswamp package,
through p-SWAMP's own ``database.get_from_database`` so the sqlite/JSON choice
stays upstream's rather than being re-decided here.

Cached for the process lifetime: it is a few tens of kilobytes and cannot change
while the server runs.
"""

import functools
import importlib.resources as resources
from pathlib import Path

from pswamp.database import get_from_database

from .wire import GridBranch, GridBus, GridDiagram, GridModel, PmuSite

DATABASE_PACKAGE = "pswamp.test_utils.sample_datasets.n44"
DATABASE_NAME = "grid_database.db"

# Country outlines and routed branches for the grid view. A committed fixture,
# like the recording beside it: tools/build_n44_grid_geometry.py regenerates it
# from that same database's single-line diagram, but needs ezdxf and pyshp, which
# are in the root package's [full] extra and not in this server's environment.
DIAGRAM_PATH = Path(__file__).parent / "data" / "n44_grid_geometry.json"

# Padding around the outermost stations, as a fraction of the bounding box, so
# markers near an edge are not clipped by the viewport the client derives.
BBOX_MARGIN = 0.06


def _db_kwargs() -> dict:
    path = resources.files(DATABASE_PACKAGE) / DATABASE_NAME
    return {"type": "sqlite", "file_path": str(path)}


def _optional(value):
    """sqlite gives back numpy scalars and NaNs; pydantic wants neither."""
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if value != value else value


@functools.lru_cache(maxsize=1)
def load_grid_model() -> GridModel:
    db = _db_kwargs()

    pmus = get_from_database(db, "pmus")
    buses = get_from_database(db, "bus")
    lines = get_from_database(db, "line")
    trafos = get_from_database(db, "trafo")

    coords = {
        str(row["name"]): (float(row["lon"]), float(row["lat"]))
        for _, row in pmus.iterrows()
    }

    bus_rows = [
        GridBus(
            name=str(row["name"]),
            v_nom=_optional(row.get("V_n")),
            area=None if row.get("Area") is None else str(row.get("Area")),
            lon=coords.get(str(row["name"]), (None, None))[0],
            lat=coords.get(str(row["name"]), (None, None))[1],
        )
        for _, row in buses.iterrows()
    ]

    branches = [
        GridBranch(
            name=str(row["name"]),
            from_bus=str(row["from_bus"]),
            to_bus=str(row["to_bus"]),
            kind=kind,
        )
        for table, kind in ((lines, "line"), (trafos, "trafo"))
        if table is not None
        for _, row in table.iterrows()
    ]

    pmu_sites = [
        PmuSite(name=name, lon=lon, lat=lat) for name, (lon, lat) in coords.items()
    ]

    lons = [site.lon for site in pmu_sites]
    lats = [site.lat for site in pmu_sites]
    pad_lon = (max(lons) - min(lons)) * BBOX_MARGIN
    pad_lat = (max(lats) - min(lats)) * BBOX_MARGIN

    return GridModel(
        buses=bus_rows,
        branches=branches,
        pmus=pmu_sites,
        bbox=(
            min(lons) - pad_lon,
            min(lats) - pad_lat,
            max(lons) + pad_lon,
            max(lats) + pad_lat,
        ),
        diagram=GridDiagram.model_validate_json(DIAGRAM_PATH.read_text()),
    )
