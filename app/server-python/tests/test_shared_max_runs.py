"""``<APP>_MAX_RUNS``: an app's run cap, read by ``run_registry``."""

from __future__ import annotations

import pytest

import shared


def test_unset_is_the_default(monkeypatch):
    monkeypatch.delenv("PMU_TEST_STREAMER_MAX_RUNS", raising=False)
    assert shared.max_runs("pmu-test-streamer") == shared.DEFAULT_MAX_RUNS == 8


def test_set_is_the_cap(monkeypatch):
    monkeypatch.setenv("PMU_TEST_STREAMER_MAX_RUNS", " 32 ")
    assert shared.max_runs("pmu-test-streamer") == 32


@pytest.mark.parametrize("value", ["0", "-3", "eight", "2.5"])
def test_anything_else_is_refused_by_name(monkeypatch, value):
    monkeypatch.setenv("PMU_TEST_STREAMER_MAX_RUNS", value)
    with pytest.raises(ValueError, match="PMU_TEST_STREAMER_MAX_RUNS"):
        shared.max_runs("pmu-test-streamer")


def test_the_registry_takes_it_unless_given_one(monkeypatch):
    monkeypatch.setenv("PMU_TEST_STREAMER_MAX_RUNS", "16")
    pipeline = shared.app_pipeline("pmu-test-streamer")
    assert shared.run_registry(pipeline).max_runs == 16
    assert shared.run_registry(pipeline, max_runs=3).max_runs == 3
    monkeypatch.setenv("PMU_TEST_STREAMER_MAX_RUNS", "not read when given")
    assert shared.run_registry(pipeline, max_runs=3).max_runs == 3
