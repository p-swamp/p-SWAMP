"""The example sources: the sample recording, the synthetic live feed, and the
recording again from the remote data stub."""

from __future__ import annotations

from datetime import timedelta

import pytest

from pswamp_core.datagateway import TimeRange
from pswamp_core.testing import DataClientConformance
from pswamp_modules.sources.live_client import LIVE_STREAM_ID, LiveSyntheticClient
from pswamp_modules.sources.sample_client import (
    EPOCH,
    LINE_TRIP_PATH,
    LINE_TRIP_STREAM_ID,
    STREAM_ID,
    LineTripRecordingClient,
    SampleRecordingClient,
    load_sample,
)

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


# --- the line-trip recording -------------------------------------------------------


def line_trip():
    return load_sample(LINE_TRIP_PATH, LINE_TRIP_STREAM_ID)


def test_the_line_trip_recording_is_thirty_seconds_of_the_same_stations_at_10_hz():
    recording = line_trip()
    assert len(recording.frames) == 300
    assert recording.header.stations == load_sample().header.stations
    assert recording.header.data_rate == 10.0 and recording.header.n_columns == 15
    first = recording.frames[0]
    assert first.timestamp == EPOCH and first.mRID == LINE_TRIP_STREAM_ID
    steps = {b.timestamp - a.timestamp for a, b in zip(recording.frames, recording.frames[1:])}
    assert steps == {timedelta(seconds=0.1)}  # an even grid, so a module's window is what it says
    assert recording.coverage.end == EPOCH + timedelta(seconds=30)


def test_the_line_trip_is_five_seconds_in_and_the_reconnection_twenty_five():
    recording = line_trip()
    (column,) = [
        i for i in recording.header.columns(measurement="f") if recording.header.station[i] == "6500"
    ]
    f = [frame.values[column] for frame in recording.frames]  # station 6500, one value per 0.1 s
    assert all(abs(x - 50.0) < 0.005 for x in f[:51])  # steady up to and including 5.0 s
    assert all(x > 50.05 for x in f[60:250])  # islanded: its frequency sits high
    assert max(f[250:260]) > 51.0  # the swing as it reconnects
    assert abs(f[-1] - 50.0) < 0.05  # and back with the rest


class TestLineTripRecordingClient(DataClientConformance):
    @pytest.fixture
    def client_under_test(self):
        return LineTripRecordingClient()

    @pytest.fixture
    def conformance_records(self):
        return list(line_trip().frames)


def test_a_sample_file_s_frames_carry_the_mrid_of_the_client_serving_it():
    assert SampleRecordingClient().recording.frames[0].mRID == STREAM_ID
    assert LineTripRecordingClient().recording.frames[0].mRID == LINE_TRIP_STREAM_ID
    assert LineTripRecordingClient.from_env("recording").name == "recording"


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


# --- the same recording, from the remote data stub ----------------------------------------


class TestTheSampleFromTheRemoteDataStub(DataClientConformance):
    @pytest.fixture
    def client_under_test(self):
        import httpx
        from remote_data_stub import create_app

        from pswamp_core.datagateway.clients.remote_data import RemoteDataClient

        transport = httpx.ASGITransport(app=create_app(SampleRecordingClient()))
        http = httpx.AsyncClient(transport=transport, base_url="http://stub")
        return RemoteDataClient("remote", "http://stub", http_client=http)

    @pytest.fixture
    def conformance_records(self):
        return list(load_sample().frames)
