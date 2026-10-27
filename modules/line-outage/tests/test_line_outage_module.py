"""The Line outage module: currents in, the branches carrying none out."""

from datetime import datetime, timedelta, timezone

from pswamp_models.line_outage import LineOutageResult
from pswamp_models.pmu import PmuFrame, PmuHeader
from pswamp_modules.line_outage import LineOutageModule

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
RATE = 50.0


def header(units: str = "A") -> PmuHeader:
    """Two stations, each with a frequency and the current of the one line between them."""
    return PmuHeader(
        station=["A", "A", "A", "B", "B", "B"],
        channel=["f", "I_AB", "I_AB", "f", "I_AB", "I_AB"],
        measurement=["f", "I_Magnitude", "I_Angle", "f", "I_Magnitude", "I_Angle"],
        units=["Hz", units, "deg", "Hz", units, "deg"],
        data_rate=RATE,
        analog=["fa", "ia", "ia", "fb", "ib", "ib"],
    )


def frames(currents: list[tuple[float | None, float | None]], units: str = "A") -> list[PmuFrame]:
    h = header(units)
    return [
        PmuFrame(mRID="test", timestamp=T0 + timedelta(seconds=k / RATE), header=h, values=[50.0, a, 0.0, 50.0, b, 0.0])
        for k, (a, b) in enumerate(currents)
    ]


def results(module: LineOutageModule, stream: list[PmuFrame]) -> list[LineOutageResult]:
    return [message for frame in stream for message in module.run(frame)]


def test_a_healthy_line_is_reported_connected_every_evaluation():
    published = results(LineOutageModule(), frames([(400.0, 400.0)] * 100))  # 2 s
    assert 9 <= len(published) <= 10  # 5 a second, once the 0.2 s window has filled
    assert all(r.result.changes == [] and r.result.disconnected == [] for r in published)
    assert published[-1].result.status == "OK"


def test_a_trip_is_one_disconnect_then_one_connect():
    stream = frames([(400.0, 400.0)] * 50 + [(0.0, 0.0)] * 50 + [(400.0, 400.0)] * 50)
    published = results(LineOutageModule(), stream)
    changes = [(c.kind, sorted((m.station, m.analog) for m in c.currents)) for r in published for c in r.result.changes]
    assert changes == [
        ("disconnect", [("A", "ia"), ("B", "ib")]),
        ("connect", [("A", "ia"), ("B", "ib")]),
    ]
    out = [r for r in published if r.result.disconnected]
    assert out and all(r.result.status == "Alert" for r in out)
    assert {m.channel for m in out[0].result.disconnected} == {"I_AB"}


def test_kiloamperes_are_amperes_too():
    published = results(LineOutageModule(), frames([(0.4, 0.4)] * 50, units="kA"))  # 400 A
    assert published[-1].result.disconnected == []


def test_a_current_with_no_value_keeps_its_state():
    stream = frames([(400.0, None)] * 50)
    assert results(LineOutageModule(), stream)[-1].result.disconnected == []


def test_a_branch_out_from_the_start_is_a_disconnect_at_once():
    first = results(LineOutageModule(), frames([(0.0, 0.0)] * 20))[0].result
    assert [c.kind for c in first.changes] == ["disconnect"] and len(first.disconnected) == 2


def test_reset_forgets_what_was_out():
    module = LineOutageModule()
    results(module, frames([(0.0, 0.0)] * 20))
    module.reset()
    first = results(module, frames([(0.0, 0.0)] * 20))[0].result
    assert [c.kind for c in first.changes] == ["disconnect"]  # reported again, not taken as known
