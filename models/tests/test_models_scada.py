"""A SCADA scan: the latest value of every SCADA measurement, at once."""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from pswamp_models.scada import AnalogReading, DiscreteReading, ScadaScan

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def scan(**changes) -> ScadaScan:
    return ScadaScan(
        timestamp=T0,
        source="rtsim-from-cim",
        sim_time=12.0,
        cimReferenceId="model",
        analogs=[AnalogReading(mRID="p1", value=-230.5)],
        discretes=[DiscreteReading(mRID="pos1", value=1)],
        **changes,
    )


def test_a_scan_is_a_versioned_message_with_its_own_topic():
    assert ScadaScan.topic_name() == "scada.scan"
    assert scan().version == "v1"


def test_a_scan_round_trips_through_json():
    message = scan()
    assert ScadaScan.model_validate_json(message.model_dump_json()) == message


def test_a_discrete_is_an_integer_and_an_analog_a_finite_number():
    assert scan().discretes[0].value == 1
    with pytest.raises(ValidationError):
        DiscreteReading(mRID="pos1", value=0.5)
    with pytest.raises(ValidationError):
        AnalogReading(mRID="p1", value=math.nan)


def test_a_scan_may_be_empty_but_says_when_and_from_what():
    empty = scan().model_copy(update={"analogs": [], "discretes": []})
    assert empty.sim_time == 12.0
    with pytest.raises(ValidationError):
        ScadaScan(timestamp=T0, sim_time=0.0)  # no source
