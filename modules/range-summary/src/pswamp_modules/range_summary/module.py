# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``RangeSummaryModule``: a batch query, answered by a module reading the sources.

It reads no topic (``inputs = ()``) and only answers
``SummarizeRangeCommand``: it reads ``[offset_s, end_offset_s)`` of a
recording from its own ``SourceSet`` (``reads_sources``) and publishes a summary.
Reading the sources awaits, so it answers in ``ahandle`` rather than
``handle``; from a script, ``run_command`` runs that on a loop of its own.
It runs wherever its host runs; in compose, in a worker of its own. A range
it cannot summarize (a live source, nothing in the range) is refused, and the
refusal comes back as an ``ErrorEvent``. Its messages are in
``pswamp_models.range_summary``.
"""

from __future__ import annotations

from datetime import timedelta

from pswamp_core.command_routing import CommandRefused
from pswamp_core.modules import Module
from pswamp_models.pmu import PmuFrame
from pswamp_models.range_summary import RangeSummary, RangeSummaryResult, SummarizeRangeCommand

__all__ = ["RangeSummaryModule"]


class RangeSummaryModule(Module):
    name = "range-summary"
    outputs = (RangeSummaryResult,)
    commands = (SummarizeRangeCommand,)
    reads_sources = True

    def validate(self, command: SummarizeRangeCommand) -> None:
        if command.source not in self.sources.sources:
            raise CommandRefused(f"no source named {command.source!r}")
        if self.sources.kind(command.source) != "history":
            raise CommandRefused(f"{command.source} is live: there is no range to summarize")
        if command.end_offset_s <= command.offset_s:
            raise CommandRefused("the range is empty")

    async def ahandle(self, command: SummarizeRangeCommand) -> RangeSummary:
        self.sources.switch(command.source)
        coverage = await self.sources.coverage()
        start = coverage.start + timedelta(seconds=command.offset_s)
        end = coverage.start + timedelta(seconds=command.end_offset_s)
        frames, frequencies = 0, []
        async for frame in await self.sources.consume(start, end):
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
