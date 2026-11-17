"""The recorder, added to the PMU test streamer by the environment, records the live source's shared run."""

import asyncio
from pathlib import Path

from datetime import UTC, datetime
from types import SimpleNamespace

from pswamp_core.pipeline import Pipeline, PipelineRun, start_live_runs
from pswamp_core.transport import InMemoryTransport
from pswamp_models.pmu import PmuFrame, PmuHeader
from pswamp_modules.recorder import Recorder

PIPELINE = Path(__file__).resolve().parents[3] / "pipelines" / "pmu-test-streamer.toml"


async def test_a_recorder_named_by_the_environment_records_the_live_source(tmp_path, monkeypatch):
    monkeypatch.setenv("PMU_TEST_STREAMER_SOURCES", "sample:sample-replay,live:live-synthetic,recorded:recorder")
    monkeypatch.setenv("PMU_TEST_STREAMER_CIM_REFERENCE", "none")
    monkeypatch.setenv("RECORDED_DIR", str(tmp_path))
    monkeypatch.setenv("RECORDED_FEED", "live")
    monkeypatch.setenv("RECORDED_FLUSH_SECONDS", "0")
    pipeline = Pipeline.load(PIPELINE)
    (live,) = await start_live_runs(pipeline, InMemoryTransport())
    try:
        async with asyncio.timeout(5):
            while live.frame is None:
                await asyncio.sleep(0.01)
        await asyncio.sleep(0.3)
    finally:
        await live.stop()
    recorded = list(Recorder.from_env("recorded").read())
    assert recorded and all(frame.mRID == recorded[0].mRID for frame in recorded)
    assert [f.timestamp for f in recorded] == sorted(f.timestamp for f in recorded)


async def test_a_feed_gone_quiet_still_reaches_the_disk(tmp_path):
    """The run flushes a recorder after its silence: frames must not wait in memory for the next frame."""
    header = PmuHeader(station=["1"], channel=["f"], measurement=["f"], units=["Hz"], data_rate=50.0)
    frame = PmuFrame(timestamp=datetime(2026, 3, 14, 13, 5, tzinfo=UTC), mRID="test", header=header, values=[50.0])
    recorder = Recorder(dir=tmp_path, flush_seconds=0.1)
    queue: asyncio.Queue = asyncio.Queue()
    queue.put_nowait(frame)
    run = SimpleNamespace(key="test")
    task = asyncio.create_task(PipelineRun._record(run, recorder, queue))
    try:
        async with asyncio.timeout(5):
            while not list(Recorder(dir=tmp_path).read()):  # no teardown, no second frame
                await asyncio.sleep(0.05)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert list(Recorder(dir=tmp_path).read()) == [frame]
