# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``SummarizeRangeCommand``: ask the range summary module about part of a recording."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ..common.command import Command

__all__ = ["SummarizeRangeCommand"]


class SummarizeRangeCommand(Command):
    """Summarize ``[offset_s, end_offset_s)`` of a recording."""

    version: Literal["v1"] = "v1"
    source: str = Field(description="The recording: a history source of the pipeline.")
    offset_s: float = Field(ge=0, description="Seconds from the start of the recording.")
    end_offset_s: float = Field(gt=0, description="Exclusive end, in seconds from the start.")
