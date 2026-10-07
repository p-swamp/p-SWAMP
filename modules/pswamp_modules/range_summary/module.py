# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``RangeSummaryModule``: a batch query, answered by a module reading the gateway.

It reads no topic (``input_model = None``) and only answers
``SummarizeRangeCommand``: it reads ``[offset_s, end_offset_s)`` of a
recording from its own gateway (``reads_gateway``) and publishes a summary.
It runs wherever its host runs; in compose, in a worker of its own. A range
it cannot summarize (a live source, nothing in the range) is refused, and the
refusal comes back as an ``ErrorEvent``.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Literal

from pydantic import BaseModel, Field

from pswamp_core.command_routing import CommandRefused
from pswamp_core.modules import Module
from pswamp_models.common import Command, ResultEnvelope
from pswamp_models.pmu import PmuFrame

__all__ = ["RangeSummary", "RangeSummaryModule", "RangeSummaryResult", "SummarizeRangeCommand"]


class SummarizeRangeCommand(Command):
    """Summarize ``[offset_s, end_offset_s)`` of a recording."""

    version: Literal["v1"] = "v1"
    source: str = Field(description="The recording: a history source of the pipeline.")
    offset_s: float = Field(ge=0, description="Seconds from the start of the recording.")
    end_offset_s: float = Field(gt=0, description="Exclusive end, in seconds from the start.")


class RangeSummary(BaseModel):
    source: str
    offset_s: float
    end_offset_s: float
    frames: int = Field(description="Frames in the range.")
    min_frequency_hz: float
    max_frequency_hz: float
    mean_frequency_hz: float


class RangeSummaryResult(ResultEnvelope[RangeSummary]):
    version: Literal["v1"] = "v1"


class RangeSummaryModule(Module):
    name = "range-summary"
    input_model = None
    output_model = RangeSummaryResult
    commands = (SummarizeRangeCommand,)
    reads_gateway = True

    def validate(self, command: SummarizeRangeCommand) -> None:
        if command.source not in self.gateway.sources:
            raise CommandRefused(f"no source named {command.source!r}")
        if self.gateway.kind(command.source) != "history":
            raise CommandRefused(f"{command.source} is live: there is no range to summarize")
        if command.end_offset_s <= command.offset_s:
            raise CommandRefused("the range is empty")

    async def handle(self, command: SummarizeRangeCommand) -> RangeSummary:
        self.gateway.switch(command.source)
        coverage = await self.gateway.coverage()
        start = coverage.start + timedelta(seconds=command.offset_s)
        end = coverage.start + timedelta(seconds=command.end_offset_s)
        frames, frequencies = 0, []
        async for frame in await self.gateway.consume(start, end):
            if isinstance(frame, PmuFrame):
                frames += 1
                values = [frame.values[i] for i in frame.header.columns(measurement="f")]
                frequencies += [v for v in values if v is not None]
        if not frequencies:
            raise CommandRefused(f"{command.source} holds nothing in [{command.offset_s}, {command.end_offset_s}) s")
        return RangeSummary(
            source=command.source,
            offset_s=command.offset_s,
            end_offset_s=command.end_offset_s,
            frames=frames,
            min_frequency_hz=min(frequencies),
            max_frequency_hz=max(frequencies),
            mean_frequency_hz=sum(frequencies) / len(frequencies),
        )
