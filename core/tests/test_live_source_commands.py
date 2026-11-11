"""A live source that takes commands, and publishes more than its frames (ADR-016)."""

from __future__ import annotations

import asyncio
from typing import Literal

import pytest
from support import ListSource, TickingSource, take, utcnow
from test_pipeline import Halver, until

from pswamp_core.command_routing import CommandRefused
from pswamp_core.pipeline import Pipeline, PipelineRun, live_key, start_live_runs
from pswamp_core.sources import SourceModule, SourceSet
from pswamp_core.subscription import Overflow
from pswamp_core.transport import InMemoryTransport
from pswamp_models.common import Command, DataModel, ErrorEvent
from pswamp_models.player import SeekCommand, SwitchSourceCommand
from pswamp_models.pmu import PmuFrame


class Nudge(Command):
    """What the commanded source takes."""

    version: Literal["v1"] = "v1"
    amount: int = 1


class Note(DataModel):
    """What the commanded source says beside its frames."""

    version: Literal["v1"] = "v1"
    text: str


class CommandedSource(TickingSource):
    """A live source that takes ``Nudge`` (refusing a negative one) and says what it did as a ``Note``."""

    name = "commanded-source"
    outputs = (PmuFrame, Note)
    commands = (Nudge,)

    def __init__(self, source: str = "commanded", interval: float = 0.02) -> None:
        super().__init__(source, interval)
        self.nudged: list[int] = []
        self._notes: asyncio.Queue[Note] = asyncio.Queue()

    def validate(self, command: Command) -> None:
        if isinstance(command, Nudge) and command.amount < 0:
            raise CommandRefused("a nudge is never negative")

    async def ahandle(self, command: Nudge) -> None:
        self.nudged.append(command.amount)
        await self._notes.put(Note(timestamp=utcnow(), text=f"nudged by {command.amount}"))

    async def aread(self, start=None, end=None):
        frames = super().aread(start, end)
        while True:
            while not self._notes.empty():
                yield self._notes.get_nowait()
            yield await frames.__anext__()


def commanded_sources() -> SourceSet:
    return SourceSet([ListSource("rec"), CommandedSource("live")])


# -- the contract ----------------------------------------------------------------------


def test_only_a_live_source_takes_commands_of_its_own():
    with pytest.raises(TypeError, match="only a live source"):

        class CommandedHistory(SourceModule):  # noqa: F841 - its definition is what fails
            name = "commanded-history"
            kind = "history"
            commands = (Nudge,)

            def coverage(self):
                return None

            def read(self, start=None, end=None):
                return iter(())

            def handle(self, command):
                return None


def test_a_live_source_does_not_take_the_player_s_commands():
    with pytest.raises(TypeError, match="the player's"):

        class Seeking(TickingSource):  # noqa: F841
            name = "seeking-source"
            commands = (SeekCommand,)

            def handle(self, command):
                return None


def test_a_command_class_has_one_receiver_among_sources_and_modules():
    class NudgeTaker(Halver):
        commands = (Nudge,)

    with pytest.raises(ValueError, match="both take Nudge"):
        Pipeline("app", commanded_sources, modules=(NudgeTaker,))
    pipeline = Pipeline("app", commanded_sources, modules=(Halver,))
    assert pipeline.source_commands == {Nudge: "live"}


def test_a_source_s_outputs_beside_its_frames_are_topics_of_the_pipeline():
    class AlsoNote(Halver):
        commands = ()
        outputs = (type("Note", (DataModel,), {"__annotations__": {"version": str}}),)

    with pytest.raises(ValueError, match="both on topic note"):
        Pipeline("app", commanded_sources, modules=(AlsoNote,))


# -- routing -----------------------------------------------------------------------------


@pytest.fixture
async def live():
    """The shared live run of ``commanded``, and its transport."""
    transport = InMemoryTransport()
    pipeline = Pipeline("app", commanded_sources)
    runs = await start_live_runs(pipeline, transport)
    (run,) = runs
    yield run, transport
    await run.stop()


async def test_the_shared_run_hands_its_live_source_its_commands_while_it_streams(live):
    run, _ = live
    source = run.sources.instances["live"]
    await until(lambda: run.frame is not None)
    run.dispatch(Nudge(amount=2))
    run.dispatch(Nudge(amount=3))
    await until(lambda: source.nudged == [2, 3])
    seen = run.frame.timestamp
    await until(lambda: run.frame.timestamp > seen)  # the stream never stopped for them


async def test_a_command_the_live_source_refuses_is_refused_before_it_is_published(live):
    run, _ = live
    with pytest.raises(CommandRefused, match="never negative"):
        run.dispatch(Nudge(amount=-1))
    assert run.sources.instances["live"].nudged == []


async def test_a_client_run_sends_a_live_source_command_to_the_shared_run(live):
    shared, transport = live
    client = PipelineRun("a", shared.pipeline, transport)
    await client.start()  # on its recording, following nothing
    client.dispatch(Nudge(amount=5))
    await until(lambda: shared.sources.instances["live"].nudged == [5])
    assert client.sources.instances["live"].nudged == []  # its own instance never opened
    await client.stop()


async def test_what_a_live_source_says_beside_its_frames_goes_out_under_its_key(live):
    run, transport = live
    notes = transport.subscribe(Note, app="app", key=live_key("live"))
    await notes.ready(5)
    client = PipelineRun("a", run.pipeline, transport)
    await client.start()
    client.dispatch(SwitchSourceCommand(source="live"))
    await until(lambda: client.following == live_key("live"))
    await asyncio.sleep(0.1)  # its subscription to the live run is being received
    run.dispatch(Nudge(amount=4))
    ((key, note),) = await take(notes, 1)
    assert note.text == "nudged by 4" and key.startswith("live.live")
    await until(lambda: run.latest.get(Note) is not None)
    await until(lambda: client.latest.get(Note) is not None)  # a viewer of the live run hears it too
    # A note is not a frame: the cursor and the frame at it are the frames'.
    await until(lambda: run.frame is not None)
    assert isinstance(run.frame, PmuFrame) and isinstance(run.router.last_frame, PmuFrame)
    assert isinstance(client.frame, PmuFrame)
    notes.close()
    await client.stop()


async def test_a_refusal_when_the_command_is_applied_reaches_the_error_topic(live):
    run, transport = live
    errors = transport.subscribe(ErrorEvent, app="app", key=live_key("live"))
    await errors.ready(5)
    # Published by hand, as a client run does: validated only where it is applied.
    run.outbox.publish(Nudge(amount=-7), key=live_key("live"))
    ((_, error),) = await take(errors, 1)
    assert "refused nudge" in error.message and error.detail == "a nudge is never negative"
    errors.close()


async def test_the_shared_run_takes_its_source_s_commands_even_if_the_pipeline_was_read_before_it_was_configured():
    # A pipeline file's sources come from the environment (<APP>_SOURCES), which a deployment may add
    # a live source to after the pipeline was read: its shared run still takes that source's commands.
    calls = {"n": 0}

    def later_sources() -> SourceSet:
        calls["n"] += 1
        return SourceSet([ListSource("rec")] if calls["n"] == 1 else [ListSource("rec"), CommandedSource("live")])

    transport = InMemoryTransport()
    pipeline = Pipeline("app", later_sources)
    assert pipeline.source_commands == {}  # read before the live source was there
    (run,) = await start_live_runs(pipeline, transport)
    await until(lambda: run.frame is not None)
    run.dispatch(Nudge(amount=6))
    await until(lambda: run.sources.instances["live"].nudged == [6])
    with pytest.raises(CommandRefused, match="never negative"):
        run.dispatch(Nudge(amount=-1))
    await run.stop()


async def test_what_a_late_configured_source_says_beside_its_frames_still_goes_out():
    # As for its commands: a live source the environment added after the pipeline was read still has
    # what it says beside its frames published under its key, and heard by a run that follows it.
    calls = {"n": 0}

    def later_sources() -> SourceSet:
        calls["n"] += 1
        return SourceSet([ListSource("rec")] if calls["n"] == 1 else [ListSource("rec"), CommandedSource("live")])

    transport = InMemoryTransport()
    pipeline = Pipeline("app", later_sources)
    assert pipeline.source_outputs == ()  # read before the live source was there
    notes = transport.subscribe(Note, app="app", key=live_key("live"))
    await notes.ready(5)
    (run,) = await start_live_runs(pipeline, transport)
    await until(lambda: run.frame is not None)
    client = PipelineRun("a", pipeline, transport)
    await client.start()
    client.dispatch(SwitchSourceCommand(source="live"))
    await until(lambda: client.following == live_key("live"))
    await asyncio.sleep(0.1)  # its subscription to the live run is being received
    run.dispatch(Nudge(amount=3))
    ((_, note),) = await take(notes, 1)
    assert note.text == "nudged by 3"
    await until(lambda: client.latest.get(Note) is not None)
    notes.close()
    await client.stop()
    await run.stop()


async def test_what_a_live_source_says_is_never_dropped_for_its_frames(live):
    # A shared run whose outbox is full of frames still publishes every note: a report the graph's
    # writer would miss for good, where a frame is soon followed by the next.
    run, transport = live
    run.outbox.maxsize = 1
    notes = transport.subscribe(Note, app="app", key=live_key("live"), overflow=Overflow.GROW)
    await notes.ready(5)
    for amount in range(5):
        run.dispatch(Nudge(amount=amount))
    got = await take(notes, 5)
    assert sorted(note.text for _, note in got) == [f"nudged by {i}" for i in range(5)]
    notes.close()


async def test_a_router_not_on_the_live_source_refuses_its_commands():
    transport = InMemoryTransport()
    run = PipelineRun("a", Pipeline("app", commanded_sources), transport)
    await run.start()  # on its recording
    with pytest.raises(CommandRefused, match="is not running here"):
        run.router.validate(Nudge())
    run.dispatch(SwitchSourceCommand(source="live"))  # following the shared run: still not here
    await until(lambda: run.router.status().mode == "live")
    with pytest.raises(CommandRefused, match="is not running here"):
        run.router.validate(Nudge())
    await run.stop()
