# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The player's commands: what a page (or a module) asks of a run's replay.

Each class is its own address (see ``pswamp_models.common.Command``); the
player is the one receiver of every ``PlayerCommand``.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from ..common.command import Command

__all__ = [
    "PauseCommand",
    "PlayCommand",
    "PlayerCommand",
    "SeekCommand",
    "SpeedCommand",
    "StepCommand",
    "SwitchSourceCommand",
]


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
