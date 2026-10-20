"""Following the graph: an edit in the store comes back from ``Follower.changes`` as what the engine
applies, once the reader's cache policy has let the SSH profile expire, and nothing is read before."""

from __future__ import annotations

import time

import pytest

from pswamp_core.cim import SAMPLE_GRID, CimSettings, GraphVersion, connect_reader, open_store, stage
from pswamp_core.cim.testing import edit, reset
from pswamp_modules.rtsim_from_cim.follow import Follower

SETTINGS = CimSettings(cim_path=SAMPLE_GRID)
P = "3f5e0000-0000-4000-8000-0000000000"
BAY_BREAKER, ALPHA_BETA, LOAD, TRANSFORMER = P + "a1", P + "24", P + "33", P + "35"

needs_profiles = pytest.mark.skipif(not stage(SETTINGS).writable, reason="the CGMES vocabularies are not available to LazyCIM")


def follow() -> Follower:
    return Follower(connect_reader(SETTINGS), GraphVersion(open_store(SETTINGS)))


@pytest.fixture
def follower():
    yield follow()
    reset(SETTINGS)


def expire():
    """Nothing to wait for: a write moves the stamp, which the follower looks at."""


def test_nothing_changed_is_nothing_read_but_the_stamp(follower):
    time.sleep(0.3)  # nothing expires on a timer
    with follower.exporter.repo.measure() as work:
        assert not follower.changes()
    assert work.queries == 0  # the stamp is asked of the store, not through the repository


@needs_profiles
def test_a_breaker_opened_in_the_graph_is_a_switch_to_open(follower):
    edit(SETTINGS, BAY_BREAKER, open=True)
    expire()
    change = follower.changes()
    name = {mrid: name for name, mrid in follower.sim.ids["lines"].items()}[BAY_BREAKER]
    assert change.opened == {name} and not change.closed and change.model is None
    edit(SETTINGS, BAY_BREAKER, open=False)
    expire()
    assert follower.changes().closed == {name}


@needs_profiles
def test_a_load_that_draws_more_is_a_value_that_moved(follower):
    edit(SETTINGS, LOAD, p=150.0)
    expire()
    (moved,) = follower.changes().values
    assert (moved.component, moved.column, moved.new) == ("loads", "P", 150.0)


@needs_profiles
def test_a_terminal_disconnected_takes_its_line_out_live(follower):
    terminal = next(
        t.mRID for t in follower.exporter.repo.from_mRID(ALPHA_BETA).Terminals if t.sequenceNumber == 1
    )
    edit(SETTINGS, terminal, connected=False)
    expire()
    change = follower.changes()
    assert change.live and change.opened == {"Alpha-Beta 400 kV line"}  # an event, not a new model
    assert change.model is not None  # in case the line comes back to a part the model left out
    edit(SETTINGS, terminal, connected=True)
    expire()
    assert follower.changes().closed == {"Alpha-Beta 400 kV line"}


@needs_profiles
def test_a_terminal_disconnected_takes_its_transformer_out_live(follower):
    # A transformer between two substations is drawn as a line on the map (Mo-Narvik in Nordic44), and
    # taken out the same way: its row goes, which used to make the simulation start over.
    terminal = next(t.mRID for t in follower.exporter.repo.from_mRID(TRANSFORMER).Terminals if t.sequenceNumber == 1)
    edit(SETTINGS, terminal, connected=False)
    expire()
    change = follower.changes()
    assert change.live and change.transformers_out == {"Gamma 400/132"} and not change.opened
    edit(SETTINGS, terminal, connected=True)
    expire()
    back = follower.changes()
    assert back.live and back.transformers_in == {"Gamma 400/132"}
