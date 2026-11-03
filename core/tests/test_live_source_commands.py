"""A live source that takes commands, and publishes more than its frames (ADR-015)."""

from __future__ import annotations

import asyncio
from typing import Literal

import pytest
from support import ListSource, TickingSource, utcnow
from test_pipeline import Halver

from pswamp_core.command_routing import CommandRefused
from pswamp_core.pipeline import Pipeline
from pswamp_core.sources import SourceModule, SourceSet
from pswamp_models.common import Command, DataModel
from pswamp_models.player import SeekCommand
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
