"""The recorder, added to the PMU test streamer by the environment, records the live source's shared run."""

import asyncio
from pathlib import Path

from pswamp_core.pipeline import Pipeline, start_live_runs
from pswamp_core.transport import InMemoryTransport
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
