"""The result cache: results by source, class and data timestamp, shown again
at the instants they stand for."""

from __future__ import annotations

from typing import Literal

import pytest
from support import Number, NumberResult, at

from pswamp_core.messages import AppIdentity, ResultEnvelope
from pswamp_core.result_cache import ResultCache

IDENTITY = AppIdentity(name="n", uuid="u")


class OtherResult(ResultEnvelope[Number]):
    version: Literal["v1"] = "v1"


def result(seconds: float, stream: str | None = "a", value: float = 0.0, cls=NumberResult):
    return cls(timestamp=at(seconds), app=IDENTITY, stream=stream, result=Number(value=value))


def filled(*seconds: float, stream: str = "a") -> ResultCache:
    cache = ResultCache()
    for s in seconds:
        cache.put("rec", result(s, stream, value=s))
    return cache


def value_at(cache: ResultCache, seconds: float, source: str = "rec", cls=NumberResult) -> float | None:
    found = cache.at(source, cls, at(seconds))
    return None if found is None else found.result.value


def test_one_result_answers_only_for_its_own_instant():
    cache = filled(1.0)
    assert value_at(cache, 1.0) == 1.0
    assert value_at(cache, 1.05) is None and value_at(cache, 0.95) is None


def test_a_result_stands_until_the_next_one_is_due():
    cache = filled(1.0, 1.1, 1.2)  # one result every 0.1 s
    assert value_at(cache, 1.0) == 1.0 and value_at(cache, 1.05) == 1.0
    assert value_at(cache, 1.1) == 1.1 and value_at(cache, 1.19) == 1.1
    assert value_at(cache, 1.29) == 1.2
    assert value_at(cache, 1.3) is None  # one interval past the last: the next would be due
    assert value_at(cache, 0.99) is None  # before the first


def test_past_a_gap_in_the_results_there_is_no_answer():
    cache = filled(1.0, 1.1, 1.5)  # nothing was computed between 1.1 and 1.5
    assert value_at(cache, 1.19) == 1.1
    assert value_at(cache, 1.3) is None
    assert value_at(cache, 1.55) == 1.5


def test_the_interval_comes_from_one_stream_s_results_only():
    cache = ResultCache()
    cache.put("rec", result(1.0, "a", 1.0))
    cache.put("rec", result(5.0, "b", 5.0))  # another stream: its distance says nothing
    cache.put("rec", result(9.0, None, 9.0))  # no stream: nor does this
    assert value_at(cache, 1.5) is None and value_at(cache, 5.0) == 5.0
    cache.put("rec", result(5.1, "b", 5.1))  # stream b's next, though others put in between
    assert value_at(cache, 1.05) == 1.0  # the class's interval is known now, for every instant


def test_results_are_kept_apart_by_source_and_by_class():
    cache = filled(1.0, 1.1)
    cache.put("other", result(1.0, value=7.0))
    cache.put("rec", result(1.0, value=8.0, cls=OtherResult))
    assert value_at(cache, 1.0) == 1.0
    assert value_at(cache, 1.0, source="other") == 7.0
    assert value_at(cache, 1.0, cls=OtherResult) == 8.0
    assert value_at(cache, 1.0, source="nowhere") is None


def test_a_result_for_an_instant_already_held_replaces_it():
    cache = filled(1.0)
    cache.put("rec", result(1.0, "b", value=2.0))
    assert len(cache) == 1 and value_at(cache, 1.0) == 2.0


def test_at_the_cap_the_oldest_put_is_dropped():
    cache = ResultCache(max_entries=3)
    for s in (5.0, 1.0, 3.0, 2.0):  # put order, not time order
        cache.put("rec", result(s, value=s))
    assert len(cache) == 3
    assert value_at(cache, 5.0) is None  # the first put
    assert [value_at(cache, s) for s in (1.0, 2.0, 3.0)] == [1.0, 2.0, 3.0]
    cache.clear()
    assert len(cache) == 0 and value_at(cache, 1.0) is None
    with pytest.raises(ValueError):
        ResultCache(max_entries=0)
