"""The PMU test streamer: its modules, providers, pipeline and edge."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from pmu_test_streamer.live_client import LIVE_STREAM_ID, LiveSyntheticClient
from pmu_test_streamer.pipeline import gateway
from pmu_test_streamer.sample_client import DEFAULT_PATH, EPOCH, STREAM_ID, SampleRecordingClient, load_sample
from pmu_test_streamer.stats_module import FrameStatsModule, FrameStatsResult

from pswamp_core.datagateway import TimeRange
from pswamp_core.host import ModuleHost
from pswamp_core.messages import PmuFrame, PmuHeader
from pswamp_core.testing import DataClientConformance
from pswamp_core.transport import InMemoryTransport
from pswamp_core.util.tasks import cancel_and_wait

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

TWO_STATIONS = PmuHeader(
    station=["A", "A", "A", "B", "B", "B"],
    channel=["V", "V", "f", "V", "V", "f"],
    measurement=["V_Magnitude", "V_Angle", "f", "V_Magnitude", "V_Angle", "f"],
    units=["kV", "deg", "Hz", "kV", "deg", "Hz"],
    data_rate=20.0,
)


def synthetic_frame(values: list[float | None], header: PmuHeader = TWO_STATIONS, seconds: float = 0.0) -> PmuFrame:
    return PmuFrame(timestamp=T0 + timedelta(seconds=seconds), mRID="test", header=header, values=values)


async def test_frame_stats_are_computed_from_the_frame_s_own_layout():
    stats = await FrameStatsModule().process(synthetic_frame([400.0, 10.0, 50.0, 410.0, -5.0, 49.8]))
    assert stats.n_stations == 2
    assert round(stats.mean_frequency_hz, 3) == 49.9
    assert (stats.min_frequency_hz, stats.max_frequency_hz) == (49.8, 50.0)
    assert stats.angle_spread_deg == 15.0 and stats.mean_voltage_kv == 405.0


async def test_frame_stats_skip_nulls_and_follow_a_changed_layout():
    module = FrameStatsModule()
    stats = await module.process(synthetic_frame([400.0, 0.0, None, 400.0, 0.0, 50.0]))
    assert stats.n_stations == 1
    one_station = PmuHeader(station=["C"], channel=["f"], measurement=["f"], units=["Hz"], data_rate=20.0)
    stats = await module.process(synthetic_frame([49.5], header=one_station))
    assert (stats.n_stations, stats.mean_frequency_hz, stats.mean_voltage_kv) == (1, 49.5, None)
    assert module.parameters["stations"] == ["C"]


async def test_frame_stats_hosted_over_the_transport():
    broker = InMemoryTransport()
    task = asyncio.create_task(ModuleHost(FrameStatsModule, broker, app="pmu-test-streamer").serve())
    await asyncio.sleep(0)
    with broker.subscribe(FrameStatsResult, app="pmu-test-streamer", key="client-1") as results:
        frame = synthetic_frame([400.0, 1.0, 50.1, 400.0, 2.0, 50.1])
        await broker.publish(frame, app="pmu-test-streamer", key="client-1")
        key, result = await asyncio.wait_for(results.get(), 5)
    await cancel_and_wait(task)
    assert key == "client-1" and result.timestamp == frame.timestamp
    assert result.result.mean_frequency_hz == 50.1 and result.app.name == "frame-stats"


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


# --- the live feed and the configured sources -------------------------------------


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


def test_the_streamer_s_sources_are_the_sample_and_the_live_feed(monkeypatch, tmp_path):
    monkeypatch.delenv("PMU_TEST_STREAMER_DATA_CLIENTS", raising=False)
    assert gateway().sources == ["sample", "live"]
    short = tmp_path / "short.txt"
    short.write_text("\n".join(DEFAULT_PATH.read_text().splitlines()[:10]))
    monkeypatch.setenv("PMU_TEST_STREAMER_DATA_CLIENTS", "rec:pmu_test_streamer.sample_client:SampleRecordingClient")
    monkeypatch.setenv("REC_PATH", str(short))
    configured = gateway()
    assert configured.sources == ["rec"] and len(configured.active.recording.frames) == 2


async def test_the_streamer_s_frames_carry_the_cim_reference(monkeypatch):
    monkeypatch.delenv("PMU_TEST_STREAMER_CIM_REFERENCE", raising=False)
    first = await anext(await gateway().consume())
    assert first.header.cimReferenceId == "n44-cim-stub"
    monkeypatch.setenv("PMU_TEST_STREAMER_CIM_REFERENCE", "none")
    assert (await anext(await gateway().consume())).header.cimReferenceId is None
