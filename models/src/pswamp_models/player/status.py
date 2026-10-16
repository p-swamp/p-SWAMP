# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``PlayerStatus``: what a run's player is doing."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from ..common.data_model import DataModel

__all__ = ["PlayerStatus"]


class PlayerStatus(DataModel):
    """Where a run's player is and what it can do. A page renders its controls
    from this, so it never shows a button that would be refused."""

    version: Literal["v1"] = "v1"
    timestamp: datetime
    mode: Literal["live", "replay"] = Field(
        description="'replay' paces a recording; 'live' follows a live source and has no controls."
    )
    source: str = Field(description="The active source.")
    sources: list[str] = Field(description="Every source the player can switch to, in declared order.")
    cursor: datetime | None = Field(description="The instant of the last frame played.")
    speed: float = Field(description="Speed multiplier; 1 is real time.")
    paused: bool
    loop: bool = Field(description="The replay starts over at the end of the recording.")
    ended: bool = Field(description="The replay reached its end and stopped.")
    can_seek: bool = Field(description="Seek, step and speed apply (replay mode).")
    coverage_start: datetime | None = Field(description="Start of the recording; null when live.")
    coverage_end: datetime | None = Field(description="Exclusive end of the recording; null when live.")
    range_end: datetime | None = Field(
        default=None, description="Exclusive end of a chunk being played; null otherwise."
    )
    error: str | None = Field(
        default=None, description="Why the stream stopped, when a provider failed; null otherwise."
    )
