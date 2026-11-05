"""Each line end's permanent current limit, read from the graph's ``CurrentLimit``s: the one with no
acceptable duration, else the longest-lasting. Over a store of the test's own with limits added (the
sample grid has none)."""

from __future__ import annotations

import pytest

pytest.importorskip("lazycim")

from test_cim_store import LINE, grid, store, writer  # noqa: E402, F401

from pswamp_core.cim import connect_reader, current_limits  # noqa: E402


def test_a_line_end_s_limit_is_the_one_it_can_carry_for_ever(store):  # noqa: F811
    repo = writer(store)
    end_1, end_2 = sorted(repo.from_mRID(LINE).Terminals, key=lambda t: t.sequenceNumber)
    permanent = repo.L.OperationalLimitType(name="PATL")
    temporary = repo.L.OperationalLimitType(name="TATL", acceptableDuration=600.0)
    at_1 = repo.L.OperationalLimitSet(name="Alpha-Beta end 1", Terminal=end_1)
    repo.L.CurrentLimit(name="PATL", value=1500.0, OperationalLimitSet=at_1, OperationalLimitType=permanent)
    repo.L.CurrentLimit(name="TATL", value=1800.0, OperationalLimitSet=at_1, OperationalLimitType=temporary)
    at_2 = repo.L.OperationalLimitSet(name="Alpha-Beta end 2", Terminal=end_2)
    repo.L.CurrentLimit(name="TATL", value=1700.0, OperationalLimitSet=at_2, OperationalLimitType=temporary)
    repo.commit()
    limits = current_limits(connect_reader(store=store))
    assert limits == {(LINE, 1): 1500.0, (LINE, 2): 1700.0}  # end 2 has only a temporary one: the longest


def test_a_grid_without_limits_has_none(store):  # noqa: F811
    assert current_limits(connect_reader(store=store)) == {}
