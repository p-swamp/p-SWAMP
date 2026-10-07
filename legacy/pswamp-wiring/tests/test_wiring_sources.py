"""The example sources: the sample recording and the synthetic live feed."""

from __future__ import annotations

from datetime import timedelta

import pytest

from pswamp_core.datagateway import TimeRange
from pswamp_core.testing import DataClientConformance
from pswamp_modules.sources.live_client import LIVE_STREAM_ID, LiveSyntheticClient
from pswamp_modules.sources.sample_client import EPOCH, STREAM_ID, SampleRecordingClient, load_sample

# --- the sample recording ---------------------------------------------------------


def test_the_sample_is_sixty_frames_of_five_stations_at_20_hz():
    recording = load_sample()
    assert len(recording.frames) == 60
    assert recording.header.stations == ["3000", "3245", "5100", "6500", "7000"]
    assert recording.header.data_rate == 20.0 and recording.header.n_columns == 15
    first = recording.frames[0]
    assert first.timestamp == EPOCH + timedelta(seconds=0.05) and first.mRID == STREAM_ID
    assert recording.coverage.end == EPOCH + timedelta(seconds=3.05)


class TestSampleRecordingClient(DataClientConformance):
    @pytest.fixture
    def client_under_test(self):
        return SampleRecordingClient()

    @pytest.fixture
    def conformance_records(self):
        return list(load_sample().frames)


# --- the live feed ----------------------------------------------------------------


class TestLiveSyntheticClient(DataClientConformance):
    @pytest.fixture
    async def client_under_test(self):
        client = LiveSyntheticClient()
        yield client
        await client.close()


async def test_the_live_feed_ticks_the_sample_s_frames_stamped_now():
    client = LiveSyntheticClient()
    await client.open()
    stream = client.consume(TimeRange(None, None))
    first, second = await anext(stream), await anext(stream)
    await stream.aclose()
    await client.close()
    assert first.mRID == LIVE_STREAM_ID and first.header == load_sample().header
    assert 0.02 < (second.timestamp - first.timestamp).total_seconds() < 0.2
