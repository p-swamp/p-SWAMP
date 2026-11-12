"""The pipeline files in pipelines/, loaded as the server and the workers load
them: their modules through the installed entry points, their sources through the
source entry points. The loader itself is tested in core/tests/test_pipeline_config.py."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

import pytest

from pswamp_core.host import serve_hosts
from pswamp_core.pipeline import Pipeline, PipelineRun
from pswamp_core.pipeline_config import main as pipeline_config_main
from pswamp_core.transport import InMemoryTransport
from pswamp_core.util.tasks import cancel_and_wait
from pswamp_models.frame_stats import FrameStatsResult
from pswamp_models.player import PlayCommand, SpeedCommand
from pswamp_models.pmu import PmuFrame
from pswamp_modules.sample_replay.sample import DEFAULT_PATH, EPOCH

PIPELINES = Path(__file__).resolve().parents[3] / "pipelines"
SAMPLE_GRID_MODEL = "3f5e0000-0000-4000-8000-000000000001"
STREAMER = PIPELINES / "pmu-test-streamer.toml"
GRID_MONITOR = PIPELINES / "grid-monitor.toml"
SIMULATION = "rtsim-from-cim"


@pytest.fixture(autouse=True)
def no_overrides(monkeypatch):
    for variable in (
        "PMU_TEST_STREAMER_SOURCES",
        "PMU_TEST_STREAMER_DATA_CLIENTS",
        "PMU_TEST_STREAMER_CIM_REFERENCE",
        "GRID_MONITOR_SOURCES",
    ):
        monkeypatch.delenv(variable, raising=False)


@pytest.mark.parametrize("path", sorted(PIPELINES.glob("*.toml")), ids=lambda p: p.name)
def test_every_pipeline_file_loads(path):
    assert pipeline_config_main(["validate", str(path)]) == 0


def test_the_streamer_s_modules_and_sources():
    pipeline = Pipeline.load(STREAMER)
    assert pipeline.app == "pmu-test-streamer"
    assert [m.name for m in pipeline.modules] == ["frame-stats", "excursion", "range-summary"]
    assert pipeline.sources().sources == ["sample", "live"]
    assert pipeline.live_sources() == ["live"]


def test_the_grid_monitor_owns_the_one_simulation():
    pipeline = Pipeline.load(GRID_MONITOR)
    assert pipeline.app == "grid-monitor"
    assert [m.name for m in pipeline.modules] == ["islanding-detection", "line-outage"]
    assert pipeline.live_sources() == ["rtsim"]
    assert pipeline.sources().instances["rtsim"].name == SIMULATION


# Each pipeline naming a live source starts a shared run of its own: a second TOPS engine,
# unsynchronised with the first. So no other pipeline names the simulation, in its file...
@pytest.mark.parametrize("path", sorted(set(PIPELINES.glob("*.toml")) - {GRID_MONITOR}), ids=lambda p: p.name)
def test_no_other_pipeline_starts_a_second_simulation(path):
    assert SIMULATION not in [s.name for s in Pipeline.load(path).sources().instances.values()]


# ...or in the <APP>_SOURCES a deployment replaces its sources with.
DEPLOYMENTS = ["docker-compose.yml", *sorted(str(p.relative_to(PIPELINES.parent)) for p in (PIPELINES.parent / "k8s").rglob("*.yaml"))]


@pytest.mark.parametrize("deployment", DEPLOYMENTS)
def test_no_deployment_adds_the_simulation_to_another_pipeline(deployment):
    text = (PIPELINES.parent / deployment).read_text()
    lines = text.splitlines()
    named = [
        line.strip()
        for i, line in enumerate(lines)
        if SIMULATION in line and ("_SOURCES" in line or "_SOURCES" in lines[i - 1])
    ]
    assert named == []


def test_the_environment_still_names_the_streamer_s_sources(monkeypatch, tmp_path):
    pipeline = Pipeline.load(STREAMER)
    short = tmp_path / "short.txt"
    short.write_text("\n".join(DEFAULT_PATH.read_text().splitlines()[:10]))
    monkeypatch.setenv("PMU_TEST_STREAMER_SOURCES", "rec:sample-replay")
    monkeypatch.setenv("REC_PATH", str(short))  # the source's own {NAME}_{SETTING}
    configured = pipeline.sources()
    assert configured.sources == ["rec"] and len(configured.active.recording.frames) == 2


async def test_the_streamer_s_frames_carry_the_cim_reference(monkeypatch):
    pipeline = Pipeline.load(STREAMER)
    first = await anext(await pipeline.sources().consume())
    assert first.header.cimReferenceId == SAMPLE_GRID_MODEL  # the grid in the CIM graph (conftest)
    monkeypatch.setenv("PMU_TEST_STREAMER_CIM_REFERENCE", "none")
    assert (await anext(await pipeline.sources().consume())).header.cimReferenceId is None


async def test_a_streamer_run_plays_the_sample_through_frame_stats():
    pipeline = Pipeline.load(STREAMER)
    transport = InMemoryTransport()
    hosts = asyncio.create_task(serve_hosts(pipeline.hosts(transport)))
    run = PipelineRun("client-1", pipeline, transport)
    await run.start()
    try:
        assert run.router.status().sources == ["sample", "live"]
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
