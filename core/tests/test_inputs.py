"""The input helpers on their own: the ``Latest`` join, and ``@on`` marks."""

from __future__ import annotations

from typing import Literal

import pytest
from support import Measurement, at

from pswamp_core.inputs import Latest, handlers_of, on
from pswamp_models.common import DataModel


class Fast(DataModel):
    version: Literal["v1"] = "v1"


class Slow(DataModel):
    version: Literal["v1"] = "v1"


class Estimate(DataModel):
    version: Literal["v1"] = "v1"


INPUTS = {"fast": Fast, "slow": Slow, "se": Estimate}


def join(missing: Literal["skip", "none"] = "skip") -> Latest:
    return Latest(trigger="se", max_age={"fast": 1.0, "slow": 10.0}, missing=missing).bound(INPUTS)


def test_a_trigger_with_fresh_inputs_makes_one_bundle():
    j = join()
    fast, slow, se = Fast(timestamp=at(9.5)), Slow(timestamp=at(1)), Estimate(timestamp=at(10))
    assert j.feed(fast) is None and j.feed(slow) is None
    assert j.feed(se) == {"fast": fast, "slow": slow, "se": se}


def test_only_the_newest_of_a_non_trigger_input_is_kept():
    j = join()
    j.feed(Slow(timestamp=at(9)))
    for i in range(5):
        j.feed(Fast(timestamp=at(i), mRID=str(i)))
    bundle = j.feed(Estimate(timestamp=at(4.5)))
    assert bundle["fast"].mRID == "4"


def test_a_stale_input_skips_the_call_or_passes_none():
    for missing, expected in (("skip", None), ("none", "no fast")):
        j = join(missing)
        j.feed(Fast(timestamp=at(0)))  # 2 s before the trigger, max_age 1 s
        slow = Slow(timestamp=at(1))
        j.feed(slow)
        bundle = j.feed(Estimate(timestamp=at(2)))
        if expected is None:
            assert bundle is None
        else:
            assert bundle["fast"] is None and bundle["slow"] is slow


def test_a_missing_input_skips_the_call_or_passes_none():
    assert join("skip").feed(Estimate(timestamp=at(1))) is None
    se = Estimate(timestamp=at(1))
    assert join("none").feed(se) == {"fast": None, "slow": None, "se": se}


def test_age_is_message_time_and_an_unstamped_or_newer_input_is_fresh():
    j = join()
    j.feed(Fast())  # no timestamp: cannot be judged, so fresh
    j.feed(Slow(timestamp=at(100)))  # newer than the trigger: fresh
    assert j.feed(Estimate(timestamp=at(3))) is not None


def test_only_the_trigger_calls():
    j = Latest(trigger="se").bound(INPUTS)
    for _ in range(3):
        assert j.feed(Fast(timestamp=at(0))) is None
        assert j.feed(Slow(timestamp=at(0))) is None
    assert j.feed(Estimate(timestamp=at(9999))) is not None  # no max_age: never stale


def test_each_bound_join_has_its_own_state_and_an_unknown_class_is_refused():
    declared = Latest(trigger="se", missing="none")
    a, b = declared.bound(INPUTS), declared.bound(INPUTS)
    a.feed(Fast(timestamp=at(0)))
    assert b.feed(Estimate(timestamp=at(0)))["fast"] is None
    with pytest.raises(TypeError, match="not one of the inputs"):
        a.feed(Measurement())


@pytest.mark.parametrize(
    ("declared", "match"),
    [
        (Latest(trigger="nope"), "trigger"),
        (Latest(trigger="se", max_age={"other": 1.0}), "max_age names"),
        (Latest(trigger="se", max_age={"se": 1.0}), "the trigger"),
        (Latest(trigger="se", missing="drop"), "missing"),  # type: ignore[arg-type]
    ],
)
def test_a_join_that_does_not_fit_its_inputs_is_refused(declared, match):
    with pytest.raises(TypeError, match=match):
        declared.check(INPUTS)


def test_two_inputs_of_one_class_are_refused():
    with pytest.raises(TypeError, match="same class"):
        Latest(trigger="a").check({"a": Fast, "b": Fast})


def test_on_marks_handlers_and_a_subclass_inherits_or_overrides_them():
    class Base:
        @on(Fast)
        def fast(self, message): ...

        @on(Slow)
        def slow(self, message): ...

    class Child(Base):
        def slow(self, message): ...  # unmarked override: no longer a handler

        @on(Estimate)
        def estimate(self, message): ...

    assert handlers_of(Base) == {Fast: "fast", Slow: "slow"}
    assert handlers_of(Child) == {Fast: "fast", Estimate: "estimate"}

    class Twice(Base):
        @on(Fast)
        def again(self, message): ...

    with pytest.raises(TypeError, match="both handle Fast"):
        handlers_of(Twice)
