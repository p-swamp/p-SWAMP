"""A transport key names a run, the run's id, and its stream."""

from __future__ import annotations

from pswamp_core.keys import StreamKey, next_run_id, run_of


def test_a_key_round_trips_and_a_plain_key_is_run_id_and_stream_zero():
    key = StreamKey("42", 1760512345678, 3)
    assert str(key) == "42#1760512345678.3" and StreamKey.parse(str(key)) == key
    assert StreamKey.parse("live.feed") == StreamKey("live.feed", 0, 0)
    assert str(StreamKey("live.feed")) == "live.feed"
    assert StreamKey.parse("live.feed#7.0").run == "live.feed"
    assert key.at(4) == StreamKey("42", 1760512345678, 4)


def test_a_key_that_is_not_ours_is_an_opaque_run():
    assert StreamKey.parse("a#b.c") == StreamKey("a#b.c")
    assert run_of("42#7.1") == "42" and run_of("42") == "42"


def test_run_ids_increase():
    ids = [next_run_id() for _ in range(100)]
    assert ids == sorted(set(ids))
