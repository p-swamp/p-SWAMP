# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""Build the geometry the web grid view draws: country outlines and routed branches.

Run once, by hand, to produce the artifact the server serves. It needs ``ezdxf``
and ``pyshp``, which live in p-SWAMP's ``[full]`` extra and are therefore *not*
in this project's environment -- so run it with the root project's interpreter:

    .venv/bin/python app/server-python/tools/build_n44_grid_geometry.py

Nothing that *consumes* the result needs either library: the server reads the
resulting JSON with the standard library.

What is extracted is exactly what the Qt grid view draws, through the functions
it draws them with:

* **Buses and branches** come from the ``geo`` single-line diagram, a DXF stored
  in the Nordic 44 sample database, read by ``get_buses`` and
  ``get_branches_xy_by_matching_buses`` -- the pair ``gui.grid_view``'s
  ``BusesLayer`` and ``LineLayer`` call. A branch is the polyline the diagram
  routes it along, not a straight line between its ends.
* **Country outlines** come from the shapefile ``read_geo_data`` reads for the
  ``CountriesLayer``.

Two things are done here that the Qt view does not do, both because the result
crosses a socket instead of staying in one process:

* Coordinates are converted to plain (lon, lat). The DXF is drawn with latitude
  stretched by ``DXF_ASPECT_RATIO``; that factor is divided out here and
  ``ASPECT_RATIO`` is written into the file, so the client applies the stretch
  once, to everything.
* Outlines are simplified. The shapefile carries the Norwegian coast at a detail
  no screen shows -- several megabytes of it. ``--tolerance`` is in drawing units
  (degrees of longitude) and defaults to about half a pixel at the grid view's
  opening zoom.
"""

import argparse
import json
from io import StringIO
from pathlib import Path

import ezdxf
import numpy as np

import pswamp
from pswamp.database import get_from_database
from pswamp.visualization.components.single_line_diagram import (
    get_branches_xy_by_matching_buses,
    get_buses,
)
from pswamp.visualization.countries_geo_data.read_geo_data import read_geo_data

DEFAULT_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "pswamp_web"
    / "data"
    / "n44_grid_geometry.json"
)

DATABASE_PATH = (
    Path(pswamp.__file__).parent
    / "test_utils"
    / "sample_datasets"
    / "n44"
    / "grid_database.db"
)

# Verbatim from [single_line_diagrams.geo] in examples/nordic44_rtsim/config.toml,
# which is what the Qt example's grid view is configured with.
SLD_ID = "geo"
COUNTRIES = ["Norway", "Sweden", "Denmark", "Finland"]
ASPECT_RATIO = 2
DXF_ASPECT_RATIO = 2

BRANCH_TABLES = (("line", "line"), ("trafo", "trafo"))


def simplify(points: np.ndarray, tolerance: float) -> np.ndarray:
    """Douglas-Peucker, iteratively. Keeps the end points of an open path."""
    if len(points) < 3:
        return points
    keep = np.zeros(len(points), dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        if last - first < 2:
            continue
        a, b = points[first], points[last]
        segment = b - a
        length = np.hypot(*segment)
        inner = points[first + 1 : last] - a
        if length == 0:
            distances = np.hypot(inner[:, 0], inner[:, 1])
        else:
            distances = np.abs(inner[:, 0] * segment[1] - inner[:, 1] * segment[0]) / length
        worst = int(np.argmax(distances))
        if distances[worst] > tolerance:
            split = first + 1 + worst
            keep[split] = True
            stack.extend(((first, split), (split, last)))
    return points[keep]


def country_outlines(tolerance: float, min_size: float) -> list[np.ndarray]:
    """One (lon, lat) ring per coastline or border, simplified in drawing space."""
    flat = read_geo_data(COUNTRIES)
    # read_geo_data returns every ring in one array, separated by NaN rows.
    breaks = np.where(np.isnan(flat[:, 0]))[0]
    rings = []
    start = 0
    for stop in breaks:
        ring = flat[start:stop]
        start = stop + 1
        if len(ring) < 4:
            continue
        drawn = ring * [1, ASPECT_RATIO]
        extent = drawn.max(axis=0) - drawn.min(axis=0)
        # An islet smaller than a couple of pixels is noise at any zoom the view
        # is useful at, and there are thousands of them along this coast.
        if np.hypot(*extent) < min_size:
            continue
        kept = simplify(drawn, tolerance)
        if len(kept) >= 4:
            rings.append(kept / [1, ASPECT_RATIO])
    return rings


def diagram(db_kwargs: dict):
    """Bus positions and branch polylines from the single-line diagram, as (lon, lat)."""
    diagrams = get_from_database(db_kwargs, "single_line_diagrams")
    dxf = diagrams[diagrams["name"] == SLD_ID]["data"].values[-1]
    doc = ezdxf.read(StringIO(dxf))

    to_lon_lat = np.array([1, 1 / DXF_ASPECT_RATIO])

    bus_table = get_from_database(db_kwargs, "bus")
    names, coords = get_buses(doc, bus_table["name"].to_numpy())
    buses = {str(name).strip(): xy * to_lon_lat for name, xy in zip(names, coords)}

    branches = []
    for table, kind in BRANCH_TABLES:
        rows = get_from_database(db_kwargs, table)
        if rows is None or len(rows) == 0:
            continue
        paths, _midpoints = get_branches_xy_by_matching_buses(doc, rows)
        for (_, row), path in zip(rows.iterrows(), paths):
            branches.append(
                {
                    "name": str(row["name"]),
                    "kind": kind,
                    "from_bus": str(row["from_bus"]),
                    "to_bus": str(row["to_bus"]),
                    "path": path * to_lon_lat,
                }
            )
    return buses, branches


def verify(buses: dict, branches: list[dict], outlines: list[np.ndarray]) -> None:
    """Refuse to write a file the grid view could not draw."""
    assert len(buses) == 44, f"expected the 44 Nordic 44 buses, found {len(buses)}"
    assert outlines, "no country outlines survived simplification"
    lines = [b for b in branches if b["kind"] == "line"]
    drawn = [b for b in lines if len(b["path"]) >= 2]
    # The diagram is hand-drawn and need not route every branch of the model; the
    # Qt view simply draws nothing for one it cannot find. A handful missing is
    # that, most of them missing is a diagram that no longer matches the model.
    assert len(drawn) >= 0.9 * len(lines), (
        f"only {len(drawn)} of {len(lines)} lines were found in the diagram"
    )
    for branch in drawn:
        for end, bus in ((0, "from_bus"), (-1, "to_bus")):
            gap = np.hypot(*(branch["path"][end] - buses[branch[bus]]))
            assert gap < 1e-6, f"{branch['name']} does not start/end on {branch[bus]}"


def rounded(points, ndigits: int) -> list[list[float]]:
    return [[round(float(x), ndigits), round(float(y), ndigits)] for x, y in points]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-o", "--out", type=Path, default=DEFAULT_PATH)
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.02,
        help="outline simplification tolerance, in degrees of longitude",
    )
    parser.add_argument(
        "--min-size",
        type=float,
        default=0.08,
        help="drop outline rings smaller than this, in degrees of longitude",
    )
    args = parser.parse_args()

    db_kwargs = {"type": "sqlite", "file_path": str(DATABASE_PATH)}
    buses, branches = diagram(db_kwargs)
    outlines = country_outlines(args.tolerance, args.min_size)
    verify(buses, branches, outlines)

    geometry = {
        "sld": SLD_ID,
        "countries": COUNTRIES,
        "aspect_ratio": ASPECT_RATIO,
        "buses": {name: rounded([xy], 4)[0] for name, xy in buses.items()},
        "branches": {
            branch["name"]: rounded(branch["path"], 4)
            for branch in branches
            if len(branch["path"]) >= 2
        },
        "outlines": [rounded(ring, 3) for ring in outlines],
    }
    args.out.write_text(json.dumps(geometry, separators=(",", ":")) + "\n")

    n_points = sum(len(ring) for ring in outlines)
    undrawn = [b["name"] for b in branches if len(b["path"]) < 2]
    if undrawn:
        print(f"not in the diagram, so not drawn: {', '.join(undrawn)}")
    print(
        f"wrote {args.out} ({args.out.stat().st_size / 1e3:.0f} kB): "
        f"{len(buses)} buses, {len(geometry['branches'])} of {len(branches)} branches, "
        f"{len(outlines)} outline rings / {n_points} points"
    )


if __name__ == "__main__":
    main()
