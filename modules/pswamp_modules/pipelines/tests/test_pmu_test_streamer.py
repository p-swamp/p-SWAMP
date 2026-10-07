"""The PMU test streamer's pipeline: its configured sources, and a run of it."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from pswamp_core.host import serve_hosts
from pswamp_core.pipeline import PipelineRun
from pswamp_core.transport import InMemoryTransport
from pswamp_core.util.tasks import cancel_and_wait
from pswamp_models.player import PlayCommand, SpeedCommand
from pswamp_models.pmu import PmuFrame
from pswamp_modules.frame_stats import FrameStatsResult
from pswamp_modules.pipelines.pmu_test_streamer import PIPELINE, gateway
from pswamp_modules.sources.sample_client import DEFAULT_PATH, EPOCH


def test_the_streamer_s_sources_are_the_sample_and_the_live_feed(monkeypatch, tmp_path):
    monkeypatch.delenv("PMU_TEST_STREAMER_DATA_CLIENTS", raising=False)
    assert gateway().sources == ["sample", "live"]
    short = tmp_path / "short.txt"
    short.write_text("\n".join(DEFAULT_PATH.read_text().splitlines()[:10]))
    monkeypatch.setenv("PMU_TEST_STREAMER_DATA_CLIENTS", "rec:pswamp_modules.sources.sample_client:SampleRecordingClient")
    monkeypatch.setenv("REC_PATH", str(short))
    configured = gateway()
    assert configured.sources == ["rec"] and len(configured.active.recording.frames) == 2


async def test_the_streamer_s_frames_carry_the_cim_reference(monkeypatch):
    monkeypatch.delenv("PMU_TEST_STREAMER_CIM_REFERENCE", raising=False)
    first = await anext(await gateway().consume())
    assert first.header.cimReferenceId == "n44-cim-stub"
    monkeypatch.setenv("PMU_TEST_STREAMER_CIM_REFERENCE", "none")
    assert (await anext(await gateway().consume())).header.cimReferenceId is None


async def test_a_streamer_run_plays_the_sample_through_frame_stats():
    transport = InMemoryTransport()
    hosts = asyncio.create_task(serve_hosts(PIPELINE.hosts(transport)))
    run = PipelineRun("client-1", PIPELINE, transport)
    await run.start()
    try:
        assert run.player.status().sources == ["sample", "live"]
        assert run.latest.get(PmuFrame).timestamp == EPOCH + timedelta(seconds=0.05)  # shown while paused
        run.dispatch(SpeedCommand(speed=10))
        run.dispatch(PlayCommand())
        for _ in range(200):
            stats = run.latest.get(FrameStatsResult)
            if stats is not None and stats.result.n_stations == 5:
                break
            await asyncio.sleep(0.01)
        assert stats.result.n_stations == 5 and 49 < stats.result.mean_frequency_hz < 51
    finally:
        await run.stop()
        await cancel_and_wait(hosts)
