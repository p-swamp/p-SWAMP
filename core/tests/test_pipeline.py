"""A pipeline run end to end over the in-memory transport, with its modules hosted."""

from __future__ import annotations

import asyncio
from typing import Literal

import pytest
from support import ListSource, Number, NumberResult, TickingSource
from test_modules import HalveCommand, Halver

from pswamp_core.command_routing import CommandRefused, NoReceiver
from pswamp_core.host import serve_hosts
from pswamp_core.modules import Module
from pswamp_core.pipeline import Pipeline, PipelineRun, start_live_runs
from pswamp_core.sources import SourceSet
from pswamp_core.transport import InMemoryTransport
from pswamp_core.util.tasks import cancel_and_wait
from pswamp_models.common import Command, ErrorEvent, ResultEnvelope
from pswamp_models.player import PauseCommand, PlayCommand, SeekCommand, SwitchSourceCommand
from pswamp_models.pmu import PmuFrame


class FrameCounter(Module):
    """Counts frames; pauses the player at the fifth, to show a module commanding it."""

    name = "counter"
    inputs = (PmuFrame,)
    outputs = (NumberResult, PauseCommand)

    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def process(self, frame: PmuFrame) -> list:
        self.count += 1
        number = Number(value=self.count)
        return [number, PauseCommand()] if self.count == 5 else number


def sources() -> SourceSet:
    return SourceSet([ListSource("rec")])


class Unanswered(Command):
    version: Literal["v1"] = "v1"


async def until(condition, timeout: float = 5.0) -> None:
    async def poll():
        while not condition():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(poll(), timeout)


@pytest.fixture
async def hosted():
    """A run of a pipeline, its modules hosted over one in-memory transport."""
    started = []

    async def start(*modules):
        transport = InMemoryTransport()
        pipeline = Pipeline("app", sources, modules=modules)
        hosts = asyncio.create_task(serve_hosts(pipeline.hosts(transport)))
        run = PipelineRun("client-1", pipeline, transport)
        await run.start()
        started.append((run, hosts))
        return run

    yield start
    for run, hosts in started:
        await run.stop()
        await cancel_and_wait(hosts)


def test_a_command_class_has_one_receiver():
    class Seeker(Halver):
        commands = (SeekCommand,)

    with pytest.raises(ValueError, match="player"):
        Pipeline("app", sources, modules=(Seeker,))
    with pytest.raises(ValueError, match="both take"):
        Pipeline("app", sources, modules=(Halver, Halver))


def test_two_classes_of_one_name_cannot_share_a_topic():
    class Pauser(Halver):
        commands = (type("PauseCommand", (Command,), {}),)  # the player's command's name, so its topic

    with pytest.raises(ValueError, match="both on topic pause.command"):
        Pipeline("app", sources, modules=(Pauser,))

    class AlsoNumberResult(Halver):
        commands = ()
        outputs = (type("NumberResult", (ResultEnvelope[Number],), {}),)

    with pytest.raises(ValueError, match="both on topic number.result"):
        Pipeline("app", sources, modules=(FrameCounter, AlsoNumberResult))


def test_a_command_a_module_sends_needs_a_receiver():
    class Asker(Halver):
        outputs = (NumberResult, Unanswered)

    with pytest.raises(ValueError, match="sends Unanswered, which nothing in the pipeline takes"):
        Pipeline("app", sources, modules=(Asker,))
    pipeline = Pipeline("app", sources, modules=(FrameCounter,))  # PauseCommand: the player takes it
    assert pipeline.outputs == (NumberResult, PauseCommand) and pipeline.results == (NumberResult,)


async def test_frames_reach_the_module_and_its_results_come_back(hosted):
    run = await hosted(FrameCounter)
    with run.changes() as changes:
        run.dispatch(PlayCommand())
        await until(lambda: run.latest.get(NumberResult) is not None)
        await asyncio.wait_for(anext(changes), 1)
    assert run.latest.get(PmuFrame) is not None


async def test_a_module_can_command_the_player(hosted):
    run = await hosted(FrameCounter)
    run.dispatch(PlayCommand())
    await until(lambda: run.router.status().paused and run.latest.get(NumberResult) is not None and run.latest.get(NumberResult).result.value >= 5)
    assert run.router.status().paused


async def test_a_player_command_is_refused_before_it_is_published(hosted):
    run = await hosted()
    with pytest.raises(CommandRefused):
        run.dispatch(SeekCommand(offset_s=99))
    with pytest.raises(NoReceiver):
        run.dispatch(Unanswered())


async def test_a_module_command_is_answered_or_refused_where_the_module_runs(hosted):
    run = await hosted(Halver)
    run.dispatch(HalveCommand(value=8))
    await until(lambda: run.latest.get(NumberResult) is not None)
    assert run.latest.get(NumberResult).result.value == 4
    refused = HalveCommand(value=-1)
    with run.transport.subscribe(ErrorEvent, app="app") as errors:
        run.dispatch(refused)  # accepted here: the module decides
        _, error = await asyncio.wait_for(errors.get(), 5)
    assert error.request_id == refused.request_id


async def test_stopping_a_run_drops_its_module_instances():
    transport = InMemoryTransport()
    pipeline = Pipeline("app", sources, modules=(FrameCounter,))
    (host,) = pipeline.hosts(transport)
    hosting = asyncio.create_task(host.serve())
    run = PipelineRun("k", pipeline, transport)
    await run.start()
    run.dispatch(PlayCommand())
    await until(lambda: host.keys() == ["k"])
    await run.stop()
    await until(lambda: host.keys() == [])
    await cancel_and_wait(hosting)


def test_hosts_can_be_limited_to_named_modules():
    pipeline = Pipeline("app", sources, modules=(FrameCounter, Halver))
    assert [h.name for h in pipeline.hosts(InMemoryTransport(), only={"halver"})] == ["halver"]


def two_sources() -> SourceSet:
    return SourceSet([ListSource("rec"), TickingSource("tick")])


async def test_live_is_one_shared_run_that_client_runs_follow():
    transport = InMemoryTransport()
    pipeline = Pipeline("app", two_sources, modules=(FrameCounter,))
    (host,) = pipeline.hosts(transport)
    hosting = asyncio.create_task(host.serve())
    await asyncio.sleep(0)
    (live,) = await start_live_runs(pipeline, transport)
    clients = [PipelineRun(key, pipeline, transport) for key in ("a", "b")]
    for run in clients:
        await run.start()
        run.dispatch(SwitchSourceCommand(source="tick"))
    await until(lambda: all(run.frame is not None and run.frame.timestamp == live.frame.timestamp for run in clients))
    assert live.key == "live.tick" and all(run.router.status().mode == "live" for run in clients)
    # One module instance counts the live frames for everyone.
    await until(lambda: all(run.latest.get(NumberResult) is not None for run in clients))
    uuids = {run.latest.get(NumberResult).app.uuid for run in clients}
    assert len(uuids) == 1 and "live.tick" in host.keys()
    # The clients' own sources never opened the live source.
    assert all(run.sources.instances["tick"].opened == 0 for run in clients)
    clients[0].dispatch(SwitchSourceCommand(source="rec"))
    await until(lambda: clients[0].router.status().mode == "replay")
    assert clients[0].frame.timestamp == clients[0].router.last_frame.timestamp
    for run in (*clients, live):
        await run.stop()
    await cancel_and_wait(hosting)
