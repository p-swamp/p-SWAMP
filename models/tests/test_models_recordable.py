"""What a producer lets a recorder keep: ``recordable`` on the class, found by ``recordable_models()``."""

from pswamp_models.cim import CimEdits
from pswamp_models.common import Command, DataModel, ErrorEvent, ResultEnvelope, recordable_models
from pswamp_models.frame_stats import FrameStatsResult
from pswamp_models.pmu import PmuFrame
from pswamp_models.rtsim import SimEvent
from pswamp_models.scada import ScadaScan


def test_a_message_is_not_recordable_unless_its_producer_says_so():
    assert DataModel.recordable is False
    assert ErrorEvent.recordable is False
    assert Command.recordable is False


def test_the_live_sources_messages_and_every_result_are_recordable():
    found = recordable_models()
    for model in (PmuFrame, ScadaScan, SimEvent, CimEdits, FrameStatsResult):
        assert found[model.topic_name()] is model


def test_recordable_models_are_found_by_topic_and_are_the_named_classes():
    found = recordable_models()
    assert all(topic == model.topic_name() for topic, model in found.items())
    assert ResultEnvelope not in found.values()  # the generic base is not a message
    assert not any("[" in model.__name__ for model in found.values())  # nor is ResultEnvelope[FrameStats]
    assert list(found) == sorted(found)


def test_a_result_body_is_recordable_by_inheritance():
    assert FrameStatsResult.recordable is True
