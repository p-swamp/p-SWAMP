"""Tests for the grid model: that the committed diagram still fits the topology.

The diagram the grid view draws (``pswamp_web/data/n44_grid_geometry.json``) is
a fixture generated ahead of time by ``tools/build_n44_grid_geometry.py``, from
the same database the topology beside it is read from at run time. Nothing
regenerates it automatically -- the tool needs libraries this environment does
not have -- so the two can drift, and a drifted diagram does not fail: the view
just silently draws less. These tests are what turns that into a failure.

Hermetic: reads the committed fixture and the sample database, nothing else.
"""

import math

from pswamp_web.grid_model import load_grid_model

# Hand-drawn, so it need not route every branch of the model; the Qt view draws
# nothing for one it cannot find either. These are the ones it is known to omit.
NOT_IN_THE_DIAGRAM = {"L5102-6001", "T5500-5501"}


def test_every_bus_of_the_model_has_a_place_in_the_diagram():
    model = load_grid_model()
    assert set(model.diagram.buses) == {bus.name for bus in model.buses}
    assert len(model.diagram.buses) == 44


def test_the_diagram_routes_the_branches_of_the_model():
    model = load_grid_model()
    in_model = {branch.name for branch in model.branches}
    routed = set(model.diagram.branches)
    # Nothing drawn that the model does not have, and nothing newly missing.
    assert routed <= in_model
    assert in_model - routed == NOT_IN_THE_DIAGRAM


def test_a_route_runs_from_its_from_bus_to_its_to_bus():
    # The client spreads a bus's height along the branch by distance from
    # `from_bus`, so a route stored the other way round would slope backwards.
    model = load_grid_model()
    diagram = model.diagram
    for branch in model.branches:
        route = diagram.branches.get(branch.name)
        if route is None:
            continue
        assert math.dist(route[0], diagram.buses[branch.from_bus]) < 1e-3, branch.name
        assert math.dist(route[-1], diagram.buses[branch.to_bus]) < 1e-3, branch.name


def test_outlines_cover_the_grid():
    diagram = load_grid_model().diagram
    lons = [lon for ring in diagram.outlines for lon, _ in ring]
    lats = [lat for ring in diagram.outlines for _, lat in ring]
    for lon, lat in diagram.buses.values():
        assert min(lons) <= lon <= max(lons)
        assert min(lats) <= lat <= max(lats)
