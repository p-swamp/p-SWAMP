"""Messages: topics, versions, UTC timestamps, the JSON codec."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import ClassVar, Literal

import pytest
from pydantic import ValidationError
from support import HEADER, Measurement, NumberResult, at, frame

from pswamp_core.messages import (
    DataModel,
    ErrorEvent,
    PlayCommand,
    PlayerStatus,
    PmuFrame,
    PmuHeader,
    SeekCommand,
    SpeedCommand,
    SwitchSourceCommand,
    topic_from_name,
)


@pytest.mark.parametrize(
    ("name", "topic"),
    [
        ("PmuFrame", "pmu.frame"),
        ("FrameStatsResult", "frame.stats.result"),
        ("MeasurementPMUVoltage", "measurement.pmu.voltage"),
        ("N44Frame", "n.44.frame"),
    ],
)
def test_the_topic_is_derived_from_the_class_name(name, topic):
    assert topic_from_name(name) == topic


def test_topic_on_class_and_instance():
    assert PmuFrame.topic == "pmu.frame"
    assert Measurement(timestamp=at(0)).topic == "measurement"
    assert NumberResult.topic == "number.result"
    assert ErrorEvent.topic == "error.event"


def test_a_class_may_set_its_topic_and_subclasses_inherit_it():
    class Odd(DataModel):
        version: Literal["v1"] = "v1"
        topic: ClassVar[str] = "custom.topic"

    class Odder(Odd):
        pass

    assert Odd.topic == Odder.topic == "custom.topic"


def test_a_pinned_version_rejects_another():
    with pytest.raises(ValidationError):
        Measurement.model_validate({"version": "v2", "value": 1.0})


def test_timestamps_are_utc():
    assert Measurement(timestamp=datetime(2026, 1, 1, 12)).timestamp.utcoffset() == timedelta(0)
    plus_two = timezone(timedelta(hours=2))
    assert Measurement(timestamp=datetime(2026, 1, 1, 12, tzinfo=plus_two)).timestamp.hour == 10


def test_a_frame_round_trips_with_nan_as_null():
    original = frame(0.05).model_copy(update={"values": [1.0, None, float("nan"), 50.0]})
    text = original.model_dump_json()
    assert "NaN" not in text and "null" in text
    back = PmuFrame.model_validate_json(text)
    assert back.values == [1.0, None, None, 50.0]
    assert back.timestamp == original.timestamp
    assert back.header == HEADER and back.header.header_id == HEADER.header_id


def test_a_frame_s_width_must_match_its_header():
    with pytest.raises(ValidationError):
        PmuFrame(timestamp=at(0), mRID="s", header=HEADER, values=[50.0])


def test_header_rows_must_align():
    with pytest.raises(ValidationError):
        PmuHeader(station=["a", "a"], channel=["V"], measurement=["V"], units=["kV"], data_rate=20.0)


def test_header_id_is_a_content_hash_that_ignores_the_cim_reference():
    same = PmuHeader.model_validate(HEADER.model_dump(exclude={"header_id"}))
    assert same.header_id == HEADER.header_id
    other = HEADER.model_copy(update={"data_rate": 50.0})
    assert PmuHeader.model_validate(other.model_dump(exclude={"header_id"})).header_id != HEADER.header_id
    referenced = HEADER.model_copy(update={"cimReferenceId": "grid-1"})
    assert referenced.header_id == HEADER.header_id
    assert '"header_id":"' in HEADER.model_dump_json()


def test_header_column_lookup():
    assert HEADER.columns(measurement="f") == [1, 3]
    assert HEADER.columns(station="B", measurement="V_Magnitude") == [2]
    assert HEADER.stations == ["A", "B"]


def test_a_command_gets_a_request_id_and_its_name_from_its_class():
    a, b = PlayCommand(), PlayCommand()
    assert a.request_id != b.request_id
    assert PlayCommand.name == a.name == "play"
    assert SwitchSourceCommand.name == "switch.source"
    assert SwitchSourceCommand.topic == "switch.source.command"


def test_a_command_s_arguments_are_validated_fields():
    assert SeekCommand(offset_s=3).offset_s == 3
    for bad in ({}, {"offset_s": -1}, {"offset_s": 2, "end_offset_s": 2}):
        with pytest.raises(ValidationError):
            SeekCommand(**bad)
    with pytest.raises(ValidationError):
        SpeedCommand(speed=0)


def test_player_status_round_trips():
    status = PlayerStatus(
        timestamp=at(0), mode="replay", source="sample", sources=["sample", "live"],
        cursor=None, speed=1.0, paused=True, loop=True, ended=False, can_seek=True,
        coverage_start=at(0), coverage_end=at(3),
    )
    assert PlayerStatus.model_validate_json(status.model_dump_json()) == status
