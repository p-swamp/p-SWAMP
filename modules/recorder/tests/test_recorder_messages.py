"""Which messages a recorder keeps: the MESSAGES setting."""

from datetime import UTC, datetime, timedelta

import pytest
from pswamp_core.settings import MissingSettingError
from pswamp_models.pmu import PmuFrame, PmuHeader
from pswamp_models.rtsim import SimEvent
from pswamp_models.scada import AnalogReading, ScadaScan
from pswamp_modules.recorder import Recorder

T0 = datetime(2026, 3, 14, 13, 5, tzinfo=UTC)
HEADER = PmuHeader(station=["3000"], channel=["f"], measurement=["f"], units=["Hz"], data_rate=50.0)


def scan(i: int) -> ScadaScan:
    return ScadaScan(timestamp=T0 + timedelta(seconds=i), source="x", analogs=[AnalogReading(mRID="a", value=float(i))])


def test_a_recorder_keeps_frames_unless_told_otherwise(tmp_path):
    recorder = Recorder(dir=tmp_path)
    assert recorder.input_models() == (PmuFrame,)
    with pytest.raises(TypeError, match="does not read ScadaScan"):
        recorder.run(scan(0))


def test_messages_are_chosen_by_topic_or_class_name(tmp_path):
    recorder = Recorder(dir=tmp_path, messages="PmuFrame, scada.scan,SimEvent")
    assert recorder.input_models() == (PmuFrame, ScadaScan, SimEvent)
    assert recorder.queued_inputs() == recorder.input_models()


def test_an_unknown_message_is_an_error_naming_what_can_be_chosen(tmp_path):
    with pytest.raises(MissingSettingError, match=r"'Nope'.*pmu\.frame.*scada\.scan"):
        Recorder(dir=tmp_path, messages="PmuFrame,Nope")
    with pytest.raises(MissingSettingError, match="ErrorEvent"):  # a message no producer made recordable
        Recorder(dir=tmp_path, messages="ErrorEvent")


def test_the_chosen_messages_are_kept_and_read_back(tmp_path):
    recorder = Recorder(dir=tmp_path, messages="PmuFrame,ScadaScan")
    frame = PmuFrame(timestamp=T0, mRID="t", header=HEADER, values=[50.0])
    recorder.run(frame)
    recorder.run(scan(1))
    recorder.flush()
    assert list(Recorder(dir=tmp_path, messages="PmuFrame").read()) == [frame]
    assert len(recorder.store.segments()) == 1


def test_a_message_other_than_the_chosen_is_refused(tmp_path):
    recorder = Recorder(dir=tmp_path, messages="ScadaScan")
    with pytest.raises(TypeError):
        recorder.run(PmuFrame(timestamp=T0, mRID="t", header=HEADER, values=[50.0]))


def test_messages_are_read_back_by_topic_and_time_in_the_order_they_happened(tmp_path):
    recorder = Recorder(dir=tmp_path, messages="PmuFrame,ScadaScan")
    frames = [PmuFrame(timestamp=T0 + timedelta(milliseconds=500 * i), mRID="t", header=HEADER, values=[50.0]) for i in range(5)]
    scans = [scan(1), scan(2)]
    for each in (*frames, *scans):
        recorder.run(each)
    recorder.flush()
    got = list(recorder.read_messages())
    assert [m.timestamp for m in got] == sorted(m.timestamp for m in got) and len(got) == 7
    assert list(recorder.read_messages(topics=["scada.scan"])) == scans
    assert list(recorder.read_messages(T0 + timedelta(seconds=2), topics=["scada.scan"])) == [scans[1]]
    assert list(recorder.read_messages(topics=["pmu.frame"])) == frames == list(recorder.read())
    with pytest.raises(ValueError, match="nothing is recorded as"):
        list(recorder.read_messages(topics=["sim.event"]))
