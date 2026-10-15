"""A pipeline run end to end over the in-memory transport, with its modules hosted."""

from __future__ import annotations

import asyncio
from typing import Literal

import pytest
from support import ListSource, Number, NumberResult, TickingSource, take
from test_modules import HalveCommand, Halver

from pswamp_core.command_routing import CommandRefused, NoReceiver
from pswamp_core.host import serve_hosts
from pswamp_core.modules import Module
from pswamp_core.pipeline import Pipeline, PipelineRun, start_live_runs
from pswamp_core.sources import SourceModule, SourceSet
from pswamp_core.subscription import Overflow
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


def test_a_source_is_not_hosted_as_a_module():
    with pytest.raises(ValueError, match="ListSource is a source"):
        Pipeline("app", sources, modules=(ListSource,))


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


async def test_a_new_run_of_a_key_gets_fresh_instances_even_if_the_old_one_never_closed():
    transport = InMemoryTransport()
    pipeline = Pipeline("app", sources, modules=(FrameCounter,))
    (host,) = pipeline.hosts(transport)
    hosting = asyncio.create_task(host.serve())
    crashed = PipelineRun("k", pipeline, transport)
    await crashed.start()
    crashed.dispatch(PlayCommand())

    def counted(run: PipelineRun) -> float:
        result = run.latest.get(NumberResult)
        return 0 if result is None else result.result.value

    await until(lambda: counted(crashed) >= 3)
    await crashed.router.stop()  # it stops publishing, and never says PipelineClosed
    old = crashed.latest.get(NumberResult).app.uuid
    run = PipelineRun("k", pipeline, transport)
    await run.start()  # publishes the frame at the start: the first one counted
    await until(lambda: counted(run) > 0)
    assert run.latest.get(NumberResult).app.uuid != old and counted(run) == 1 and host.keys() == ["k"]
    await crashed.stop()  # its late PipelineClosed leaves the new run's instance
    await asyncio.sleep(0.05)
    assert host.keys() == ["k"]
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
    await until(
        lambda: live.frame is not None
        and all(run.frame is not None and run.frame.timestamp == live.frame.timestamp for run in clients)
    )
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


async def test_a_command_the_transport_does_not_take_in_time_goes_to_on_error():
    class NoCommands(InMemoryTransport):
        async def publish(self, message, *, app, key):
            if isinstance(message, Command):
                raise ConnectionError("broker down")
            await super().publish(message, app=app, key=key)

    reports = []
    pipeline = Pipeline("app", sources, modules=(Halver,))
    run = PipelineRun("k", pipeline, NoCommands(), on_error=lambda key, event: reports.append((key, event)))
    run.outbox.deadline = 0.1
    await run.start()
    command = HalveCommand(value=2)
    run.dispatch(command)
    await until(lambda: reports)
    ((key, event),) = reports
    assert (key, event.source, event.request_id) == ("k", "server", command.request_id)
    assert "halve" in event.message and "not delivered" in event.message and event.detail == "ConnectionError: broker down"
    await run.stop()


async def test_a_switch_stops_a_command_stuck_on_the_source_it_leaves():
    class Hangs(ListSource):
        name = "hangs"

        async def acoverage(self):
            await asyncio.Event().wait()  # a remote service that never answers

    transport = InMemoryTransport()
    run = PipelineRun("k", Pipeline("app", lambda: SourceSet([ListSource("rec"), Hangs("stuck")])), transport)
    with transport.subscribe(ErrorEvent, app="app", key="k", overflow=Overflow.GROW) as errors:
        await run.start()
        run.dispatch(SwitchSourceCommand(source="stuck"))
        await until(lambda: run.router.status().source == "stuck")  # opening it, for ever
        run.dispatch(PlayCommand())  # waits behind it
        run.dispatch(SwitchSourceCommand(source="rec"))
        await until(lambda: run.router.status().source == "rec" and run.router.last_frame is not None, timeout=2)
        (_, play), (_, switch) = await take(errors, 2)
    assert play.message == "player did not apply play: switch.source came after it"
    assert switch.message == "player stopped applying switch.source: switch.source came after it"
    assert run.router.status().paused  # the play was for the source it left
    await run.stop()


async def test_a_viewer_who_comes_to_a_failed_live_run_hears_why(monkeypatch):
    import pswamp_core.pipeline as pipeline_module

    monkeypatch.setattr(pipeline_module, "_STATUS_EVERY_S", 0.05)

    class Down(SourceModule):
        name = "down-source"
        kind = "live"

        async def aread(self, start=None, end=None):
            raise ConnectionError("no route to the PMU")
            yield  # pragma: no cover

    transport = InMemoryTransport()
    pipeline = Pipeline("app", lambda: SourceSet([ListSource("rec"), Down("pmu")]))
    (live,) = await start_live_runs(pipeline, transport)
    await until(lambda: live.router.status().error is not None)  # failed before anyone watched
    run = PipelineRun("late", pipeline, transport)
    await run.start()
    run.dispatch(SwitchSourceCommand(source="pmu"))
    await until(lambda: run.following == "live.pmu")
    assert run.router.status().error is None  # its own router opened nothing
    await until(lambda: run.status().error is not None)
    assert "no route to the PMU" in run.status().error and run.status().mode == "live"
    run.dispatch(SwitchSourceCommand(source="rec"))
    await until(lambda: run.following is None)
    assert run.status().error is None
    for each in (run, live):
        await each.stop()


class ResetCount(Command):
    version: Literal["v1"] = "v1"


class ResettableCounter(FrameCounter):
    name = "resettable"
    commands = (ResetCount,)

    def handle(self, command: ResetCount) -> None:
        self.count = 0


async def test_a_command_to_a_module_reading_the_shared_live_run_is_refused():
    transport = InMemoryTransport()
    pipeline = Pipeline("app", two_sources, modules=(ResettableCounter, Halver))
    hosting = asyncio.create_task(serve_hosts(pipeline.hosts(transport)))
    await asyncio.sleep(0)
    (live,) = await start_live_runs(pipeline, transport)
    run = PipelineRun("a", pipeline, transport)
    await run.start()
    run.dispatch(ResetCount())  # on its own replay: its own instance
    run.dispatch(SwitchSourceCommand(source="tick"))
    await until(lambda: run.following == "live.tick")
    # The counter that matters runs under live.tick, for every viewer.
    with pytest.raises(CommandRefused, match="resettable reads the shared live run"):
        run.dispatch(ResetCount())
    run.dispatch(HalveCommand(value=2))  # a module that reads no stream still answers
    await until(lambda: run.latest.get(NumberResult) is not None and run.latest.get(NumberResult).app.name == "halver")
    run.dispatch(SwitchSourceCommand(source="rec"))
    await until(lambda: run.following is None)
    run.dispatch(ResetCount())
    for each in (run, live):
        await each.stop()
    await cancel_and_wait(hosting)
