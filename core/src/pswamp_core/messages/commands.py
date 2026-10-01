# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""Commands: typed messages going upstream.

**A command's class is its address.** Each class travels on its own topic
(``SeekCommand`` → ``<app>.seek.command``), and exactly one part of a pipeline
declares that it handles it: the player, or one module. Anyone may publish a
command (the web API, a module); anyone may subscribe to its topic to watch. The
fields are the arguments, validated where the command is built.

The player's commands are here because the player is core. A module's own
commands live beside the module.

``request_id`` is generated when a command is built. Whatever answers the
command carries it: a module's result, or an ``ErrorEvent`` if it was refused.
"""

from __future__ import annotations

from typing import ClassVar, Literal
from uuid import uuid4

from pydantic import Field, model_validator

from .data_model import DataModel, topic_from_name

__all__ = [
    "Command",
    "PauseCommand",
    "PlayCommand",
    "PlayerCommand",
    "SeekCommand",
    "SpeedCommand",
    "StepCommand",
    "SwitchSourceCommand",
]


class _Name:
    """``Command.name``: the class name without ``Command``, dotted:
    ``SwitchSourceCommand`` → ``switch.source``. What logs and acks call it."""

    def __get__(self, instance: object, owner: type[Command]) -> str:
        return topic_from_name(owner.__name__.removesuffix("Command") or owner.__name__)


class Command(DataModel):
    """One upstream action. Subclass it; the subclass is the address."""

    version: Literal["v1"] = "v1"
    request_id: str = Field(default_factory=lambda: uuid4().hex)
    client_id: str | None = Field(default=None, description="The client that issued it, if any.")

    name: ClassVar[_Name] = _Name()


class PlayerCommand(Command):
    """Base of the commands the player handles."""


class PlayCommand(PlayerCommand):
    """Start or resume the replay."""


class PauseCommand(PlayerCommand):
    """Pause the replay where it is."""


class StepCommand(PlayerCommand):
    """Play ``n`` frames at once, unpaced; a negative ``n`` steps back."""

    n: int = Field(default=1, description="Frames to step; negative steps back.")


class SeekCommand(PlayerCommand):
    """Move the replay to ``offset_s`` into the recording.

    With ``end_offset_s`` it plays only ``[offset_s, end_offset_s)`` and ends
    paused there, instead of running on or looping: a chunk.
    """

    offset_s: float = Field(ge=0, description="Seconds from the start of the recording.")
    end_offset_s: float | None = Field(
        default=None, gt=0, description="Stop here instead of running on: seconds from the start."
    )
    play: bool = Field(default=False, description="Also start playing, if paused.")

    @model_validator(mode="after")
    def _end_after_start(self) -> SeekCommand:
        if self.end_offset_s is not None and self.end_offset_s <= self.offset_s:
            raise ValueError("end_offset_s must be after offset_s")
        return self


class SpeedCommand(PlayerCommand):
    """Change the replay speed."""

    speed: float = Field(gt=0, description="Speed multiplier; 1 is real time.")


class SwitchSourceCommand(PlayerCommand):
    """Read another of the pipeline's sources.

    A recording lands paused at its start; a live source is followed from now.
    """

    source: str = Field(description="The source's name, as the pipeline declares it.")
