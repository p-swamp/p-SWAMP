"""A pipeline run end to end over the in-memory transport, with its modules hosted."""

from __future__ import annotations

import asyncio
from typing import ClassVar, Literal

import pytest
from support import ListClient, Number, NumberResult, TickingClient, at
from test_modules import HalveCommand, Halver

from pswamp_core.command_routing import CommandRefused, NoReceiver
from pswamp_core.datagateway import DataGateway
from pswamp_core.host import serve_hosts
from pswamp_core.messages import (
    Command,
    ErrorEvent,
    PauseCommand,
    PlayCommand,
    PmuFrame,
    ResultEnvelope,
    SeekCommand,
    SpeedCommand,
    StepCommand,
    SwitchSourceCommand,
)
from pswamp_core.modules import Module
from pswamp_core.pipeline import Pipeline, PipelineRun, start_live_runs
from pswamp_core.result_cache import ResultCache
from pswamp_core.transport import InMemoryTransport
from pswamp_core.util.tasks import cancel_and_wait


class FrameCounter(Module):
    """Counts frames; pauses the player at the fifth, to show a module commanding it."""

    name = "counter"
    input_model = PmuFrame
    output_model = NumberResult

    def __init__(self) -> None:
        super().__init__()
        self.count = 0
        self.out = None

    async def setup(self, out) -> None:
        self.out = out

    async def process(self, frame: PmuFrame) -> Number:
        self.count += 1
        if self.count == 5:
            self.out.publish(PauseCommand())
        return Number(value=self.count)


def gateway() -> DataGateway:
    return DataGateway([ListClient("rec")])


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
        pipeline = Pipeline("app", gateway, modules=modules)
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
        Pipeline("app", gateway, modules=(Seeker,))
    with pytest.raises(ValueError, match="both take"):
        Pipeline("app", gateway, modules=(Halver, Halver))


def test_two_classes_of_one_name_cannot_share_a_topic():
    class Pauser(Halver):
        commands = (type("PauseCommand", (Command,), {}),)  # the player's command's name, so its topic

    with pytest.raises(ValueError, match="both on topic pause.command"):
        Pipeline("app", gateway, modules=(Pauser,))

    class AlsoNumberResult(Halver):
        commands = ()
        output_model = type("NumberResult", (ResultEnvelope[Number],), {})

    with pytest.raises(ValueError, match="both on topic number.result"):
        Pipeline("app", gateway, modules=(FrameCounter, AlsoNumberResult))


def test_cache_results_is_refused_where_a_result_could_differ_between_clients():
    class Cached(FrameCounter):
        cache_results = True

    Pipeline("app", gateway, modules=(Cached,))  # reads frames, takes no commands, has no warm-up

    class WithCommands(Cached):
        commands = (HalveCommand,)

    with pytest.raises(ValueError, match="WithCommands sets cache_results, but it takes commands"):
        Pipeline("app", gateway, modules=(WithCommands,))

    class Chained(Cached):
        input_model = NumberResult

    with pytest.raises(ValueError, match="it does not read frames"):
        Pipeline("app", gateway, modules=(Chained,))

    class WarmUpOnly(Cached):
        warm_up_s = 1.0

    with pytest.raises(ValueError, match="a warm-up and no reset"):
        Pipeline("app", gateway, modules=(WarmUpOnly,))

    class WithReset(WarmUpOnly):
        def reset(self) -> None:
            self.count = 0

    Pipeline("app", gateway, modules=(WithReset,))
    with pytest.raises(ValueError, match="Halver publishes NumberResult too"):
        Pipeline("app", gateway, modules=(Cached, Halver))
    Pipeline("app", gateway, modules=(FrameCounter, Halver))  # sharing is fine when nothing is cached


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
    await until(lambda: run.player.paused and run.latest.get(NumberResult) is not None and run.latest.get(NumberResult).result.value >= 5)
    assert run.player.paused


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
    pipeline = Pipeline("app", gateway, modules=(FrameCounter,))
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
    pipeline = Pipeline("app", gateway, modules=(FrameCounter, Halver))
    assert [h.name for h in pipeline.hosts(InMemoryTransport(), only={"halver"})] == ["halver"]


PIPELINE_FOR_WORKER = Pipeline("app", gateway, modules=(FrameCounter, Halver))


def two_sources() -> DataGateway:
    return DataGateway([ListClient("rec"), TickingClient("tick")])


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
    # live.frame is None until the ticker's first frame, and a client holds its
    # recording's frame until its switch lands, so check the live run first.
    await until(
        lambda: live.frame is not None
        and all(run.frame is not None and run.frame.timestamp == live.frame.timestamp for run in clients)
    )
    assert live.key == "live.tick" and all(run.player.status().mode == "live" for run in clients)
    # One module instance counts the live frames for everyone.
    await until(lambda: all(run.latest.get(NumberResult) is not None for run in clients))
    uuids = {run.latest.get(NumberResult).app.uuid for run in clients}
    assert len(uuids) == 1 and "live.tick" in host.keys()
    # The clients' own gateways never opened the live source.
    assert all(run.gateway.clients["tick"].opened == 0 for run in clients)
    clients[0].dispatch(SwitchSourceCommand(source="rec"))
    await until(lambda: clients[0].player.status().mode == "replay")
    assert clients[0].frame.timestamp == clients[0].player.last_frame.timestamp
    for run in (*clients, live):
        await run.stop()
    await cancel_and_wait(hosting)


# --- kept results: a recording's results shown again at the cursor ---------------------


class RollingResult(ResultEnvelope[Number]):
    version: Literal["v1"] = "v1"


class Rolling(Module):
    """Stands in for an analysis over the last 0.1 s (three frames at 20 Hz).
    Its result is how many frames it has had since its input last broke."""

    name = "rolling"
    input_model = PmuFrame
    output_model = RollingResult
    warm_up_s = 0.1
    cache_results = True
    #: When set, ``process`` takes one permit per frame: the test decides when
    #: each frame is done, so a result can be made to arrive late.
    gate: ClassVar[asyncio.Semaphore | None] = None

    def __init__(self) -> None:
        super().__init__()
        self.unbroken = 0

    def reset(self) -> None:
        self.unbroken = 0

    async def process(self, frame: PmuFrame) -> Number:
        if self.gate is not None:
            await self.gate.acquire()
        self.unbroken += 1
        return Number(value=self.unbroken)


def rolling(run: PipelineRun) -> RollingResult | None:
    return run.latest.get(RollingResult)


def shown(run: PipelineRun):
    """The instant of the rolling result showing; ``None`` when none shows."""
    result = rolling(run)
    return None if result is None else result.timestamp


@pytest.fixture
async def kept():
    """One pipeline over an in-memory transport, its modules hosted, and a
    cache. Yields ``start(module, source=...)``, which gives ``(run, cache,
    host)``: ``run(key)`` starts a run sharing that cache."""
    stopping = []

    async def start(module, source=gateway, live: bool = False):
        transport, cache = InMemoryTransport(), ResultCache()
        pipeline = Pipeline("app", source, modules=(module,))
        (host,) = pipeline.hosts(transport)
        hosting = asyncio.create_task(host.serve())
        await asyncio.sleep(0)
        runs = await start_live_runs(pipeline, transport) if live else []
        stopping.append((runs, hosting))

        async def run(key: str = "client-1", cache: ResultCache | None = cache) -> PipelineRun:
            one = PipelineRun(key, pipeline, transport, cache=cache)
            await one.start()
            runs.append(one)
            return one

        return run, cache, host

    yield start
    for runs, hosting in stopping:
        for one in runs:
            await one.stop()
        await cancel_and_wait(hosting)


async def test_seeking_back_over_a_played_part_shows_its_result_at_once(kept):
    start, cache, _ = await kept(Rolling)
    run = await start()
    assert len(cache) == 0 and rolling(run) is None
    run.dispatch(StepCommand(n=1))  # two frames in: still warming up
    await until(lambda: run.frame.timestamp == at(0.05))
    assert len(cache) == 0
    run.dispatch(StepCommand(n=9))  # to 0.50; results from 0.10 on
    await until(lambda: shown(run) == at(0.5))
    own = rolling(run)
    assert not run.from_cache(own) and own.stream == run.frame.stream

    run.dispatch(SeekCommand(offset_s=0.3))  # a new stream: the module's window starts over
    await until(lambda: run.frame.timestamp == at(0.3))
    again = rolling(run)
    assert again.timestamp == at(0.3) and run.from_cache(again)
    assert again.stream == own.stream != run.frame.stream  # computed on the first pass
    run.dispatch(StepCommand(n=1))
    await until(lambda: run.frame.timestamp == at(0.35))
    await asyncio.sleep(0.05)  # time for the module to answer, were it not warming up
    assert shown(run) == at(0.35) and run.from_cache(rolling(run))

    run.dispatch(StepCommand(n=1))  # 0.40 is 0.1 s into the new stream: the module's own again
    await until(lambda: shown(run) == at(0.4) and not run.from_cache(rolling(run)))
    assert rolling(run).result.value == 3

    run.dispatch(SeekCommand(offset_s=0.7))  # never played: no result, and not an old one
    await until(lambda: run.frame.timestamp == at(0.7))
    assert rolling(run) is None


async def test_another_client_on_the_recording_gets_the_first_one_s_results(kept):
    start, cache, _ = await kept(Rolling)
    first, second = await start("a"), await start("b")
    first.dispatch(StepCommand(n=10))
    await until(lambda: shown(first) == at(0.5))
    assert rolling(second) is None
    second.dispatch(SeekCommand(offset_s=0.3))
    await until(lambda: second.frame.timestamp == at(0.3))
    theirs = rolling(second)
    assert theirs.timestamp == at(0.3) and second.from_cache(theirs)
    assert theirs.app.uuid == rolling(first).app.uuid  # the first client's module instance computed it


async def test_a_result_arriving_after_a_step_back_is_still_shown(kept):
    class Gated(Rolling):
        gate = asyncio.Semaphore(0)

    start, cache, _ = await kept(Gated)
    run = await start()
    run.dispatch(StepCommand(n=9))  # to 0.45, with the module still on its first frame
    await until(lambda: run.frame.timestamp == at(0.45))
    run.dispatch(StepCommand(n=-1))  # back to 0.40, in a new stream
    await until(lambda: run.frame.timestamp == at(0.4))
    assert rolling(run) is None  # the first pass's result for 0.40 has not come yet
    for _ in range(9):
        Gated.gate.release()  # the frames of the first pass, up to 0.40
    await until(lambda: shown(run) == at(0.4))
    assert run.from_cache(rolling(run))
    Gated.gate.release()  # 0.45: kept, and not what the cursor is at
    await until(lambda: cache.at("rec", RollingResult, at(0.45)) is not None)
    assert shown(run) == at(0.4)


async def test_a_result_from_before_a_seek_is_kept_and_not_shown(kept):
    class Gated(Rolling):
        gate = asyncio.Semaphore(0)

    start, cache, _ = await kept(Gated)
    run = await start()
    run.dispatch(StepCommand(n=10))
    await until(lambda: run.frame.timestamp == at(0.5))
    run.dispatch(SeekCommand(offset_s=0))  # back to where the window was still filling
    await until(lambda: run.frame.timestamp == at(0) and run.frame.seq == 0 and len(run._recorded) == 2)
    for _ in range(11):
        Gated.gate.release()
    await until(lambda: cache.at("rec", RollingResult, at(0.5)) is not None)
    assert rolling(run) is None  # nine results came back; none is about the cursor
    assert len(cache) == 9


async def test_a_lost_frame_keeps_a_gapped_window_s_result_out_of_the_cache(kept):
    class Gated(Rolling):
        gate = asyncio.Semaphore(0)
        maxsize = 2  # its queue keeps the two newest frames

    start, cache, host = await kept(Gated)
    run = await start()
    await until(lambda: "client-1" in host.keys())
    inputs = host._slots["client-1"].inputs
    run.dispatch(StepCommand(n=8))  # frames 1 to 8 while the module holds frame 0
    await until(lambda: inputs.dropped == 6)  # 1 to 6 are gone; 7 and 8 wait
    for _ in range(3):
        Gated.gate.release()  # 0, then 7 (a gap: it starts over) and 8
    run.dispatch(StepCommand(n=2))  # 9 and 10
    for _ in range(2):
        Gated.gate.release()
    await until(lambda: shown(run) == at(0.5))
    # 0.45 is 0.1 s after frame 7: the first result, from the three frames 7, 8, 9 alone.
    assert cache.at("rec", RollingResult, at(0.45)).result.value == 3
    assert rolling(run).result.value == 4
    assert cache.at("rec", RollingResult, at(0.4)) is None and len(cache) == 2


async def test_a_chunk_s_last_result_shows_after_the_chunk_has_ended(kept):
    start, cache, _ = await kept(Rolling)
    run = await start()
    run.dispatch(SpeedCommand(speed=10))
    run.dispatch(SeekCommand(offset_s=0.2, end_offset_s=0.4, play=True))
    await until(lambda: run.player.ended)
    await until(lambda: shown(run) == at(0.35))  # the player holds no stream now
    assert not run.from_cache(rolling(run))


async def test_coming_back_from_live_shows_what_is_kept_for_the_recording(kept):
    start, cache, _ = await kept(Rolling, source=two_sources, live=True)
    run = await start()
    earlier = RollingResult(
        timestamp=at(0), app=rolling_identity(), stream="an-earlier-pass", result=Number(value=3)
    )
    cache.put("rec", earlier)  # as if some run had computed a result for the recording's first instant
    run.dispatch(SwitchSourceCommand(source="tick"))
    await until(lambda: run.following == "live.tick" and run.frame is not None)
    run.dispatch(SwitchSourceCommand(source="rec"))
    await until(lambda: run.player.status().mode == "replay" and run.following is None)
    assert rolling(run) is earlier and run.from_cache(earlier)


async def test_a_live_source_is_never_kept(kept):
    class Every(Rolling):
        warm_up_s = 0.0

    start, cache, _ = await kept(Every, source=two_sources, live=True)
    run = await start()
    await until(lambda: rolling(run) is not None)
    kept_for_the_recording = len(cache)
    run.dispatch(SwitchSourceCommand(source="tick"))
    await until(lambda: run.following == "live.tick" and rolling(run) is not None and rolling(run).timestamp > at(3600))
    live_result = rolling(run)
    await until(lambda: rolling(run) is not live_result)  # live results keep coming
    assert len(cache) == kept_for_the_recording == 1
    assert not run.from_cache(rolling(run))


async def test_without_a_cache_a_run_behaves_as_before(kept):
    start, cache, _ = await kept(Rolling)
    run = await start(cache=None)
    run.dispatch(StepCommand(n=10))
    await until(lambda: shown(run) == at(0.5))
    run.dispatch(SeekCommand(offset_s=0.3))
    await until(lambda: run.frame.timestamp == at(0.3))
    assert shown(run) == at(0.5) and not run.from_cache(rolling(run))  # the last result stays, as it always did
    assert len(cache) == 0


async def test_a_failing_cache_is_dropped_and_the_run_carries_on(kept):
    class Broken(ResultCache):
        def at(self, source, cls, instant):
            raise RuntimeError("cache is broken")

    start, _, _ = await kept(Rolling)
    run = await start(cache=Broken())
    assert run.cache is None  # dropped at the first frame
    run.dispatch(StepCommand(n=10))
    await until(lambda: shown(run) == at(0.5))
    assert run.player.status().error is None


def rolling_identity():
    from pswamp_core.messages import AppIdentity

    return AppIdentity(name="rolling", uuid="someone-else")
