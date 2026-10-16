"""The frame statistics module: on its own, and hosted over the transport."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from pswamp_core.host import ModuleHost
from pswamp_core.transport import InMemoryTransport
from pswamp_core.util.tasks import cancel_and_wait
from pswamp_models.frame_stats import FrameStatsResult
from pswamp_models.pmu import PmuFrame, PmuHeader
from pswamp_modules.frame_stats import FrameStatsModule

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


def test_frame_stats_are_computed_from_the_frame_s_own_layout():
    frame = synthetic_frame([400.0, 10.0, 50.0, 410.0, -5.0, 49.8], seconds=1.0)
    result = FrameStatsModule().run_one(frame)
    assert isinstance(result, FrameStatsResult) and result.timestamp == frame.timestamp
    stats = result.result
    assert stats.n_stations == 2
    assert round(stats.mean_frequency_hz, 3) == 49.9
    assert (stats.min_frequency_hz, stats.max_frequency_hz) == (49.8, 50.0)
    assert stats.angle_spread_deg == 15.0 and stats.mean_voltage_kv == 405.0


def test_frame_stats_skip_nulls_and_follow_a_changed_layout():
    module = FrameStatsModule()
    stats = module.run_one(synthetic_frame([400.0, 0.0, None, 400.0, 0.0, 50.0])).result
    assert stats.n_stations == 1
    one_station = PmuHeader(station=["C"], channel=["f"], measurement=["f"], units=["Hz"], data_rate=20.0)
    stats = module.run_one(synthetic_frame([49.5], header=one_station)).result
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
