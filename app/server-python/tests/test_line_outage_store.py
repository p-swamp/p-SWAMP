"""Tests for LineOutageStore: the event log, and the present state beside it.

The detector publishes only *transitions* -- a branch's current going to zero,
or coming back -- so "what is disconnected now" has to be accumulated from them.
The grid view paints a branch red from that set, which makes two things worth
pinning: that a reconnect clears what a disconnect set, and that the set survives
the log dropping its oldest entries, since the log is bounded and the grid is
not.

Hermetic: the store is pure state fed hand-built result dicts, in the shape
``LineOutageDetectionApp.run_analysis`` returns them.
"""

from pswamp_web.stores import LineOutageStore


def result(t, *events):
    return {
        "info": {"app_name": "LineOutageDetectionApp", "uuid": "app-1"},
        "parameters": {"window_length": 0.2},
        "result": {
            "time_stamp": t,
            "events": [
                {
                    "type": kind,
                    "stations": [station for station, _ in channels],
                    "measurements": [channel for _, channel in channels],
                }
                for kind, channels in events
            ],
        },
    }


# One tripped line is reported from both of its ends: the current is zero as
# seen from each.
TRIPPED = [("3244", "I[L3244-6500]_Magnitude"), ("6500", "I[L3244-6500]_Magnitude")]


def test_nothing_is_disconnected_before_any_event():
    assert LineOutageStore().disconnected() == []


def test_a_disconnect_is_named_once_however_many_ends_report_it():
    store = LineOutageStore()
    store.handle(result(20.0, ("disconnect", TRIPPED)))
    assert store.disconnected() == ["L3244-6500"]


def test_a_reconnect_clears_it():
    store = LineOutageStore()
    store.handle(result(20.0, ("disconnect", TRIPPED)))
    store.handle(result(40.0, ("connect", TRIPPED)))
    assert store.disconnected() == []
    # The log keeps both transitions, newest first.
    assert [event.kind for event in store.list()] == ["connect", "disconnect"]


def test_only_the_reconnected_element_is_cleared():
    store = LineOutageStore()
    other = [("6700", "I[T6700-6701]_Magnitude")]
    store.handle(result(20.0, ("disconnect", TRIPPED + other)))
    store.handle(result(40.0, ("connect", TRIPPED)))
    assert store.disconnected() == ["T6700-6701"]


def test_present_state_outlives_the_bounded_log():
    store = LineOutageStore(limit=2)
    store.handle(result(20.0, ("disconnect", TRIPPED)))
    for i in range(5):
        channel = [("3000", f"I[L3000-{i}]_Magnitude")]
        store.handle(result(21.0 + i, ("disconnect", channel)))
        store.handle(result(21.5 + i, ("connect", channel)))
    assert len(store.list()) == 2
    assert store.disconnected() == ["L3244-6500"]


def test_a_result_without_events_changes_nothing():
    store = LineOutageStore()
    store.handle(result(20.0, ("disconnect", TRIPPED)))
    store.handle({"result": None})
    store.handle(result(21.0))
    assert store.disconnected() == ["L3244-6500"]
