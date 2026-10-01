"""The range summary module: a batch query answered from the module's own gateway."""

from __future__ import annotations

import pytest

from pswamp_core.command_routing import CommandRefused
from pswamp_modules.pipelines.pmu_test_streamer import gateway
from pswamp_modules.range_summary import RangeSummaryModule, SummarizeRangeCommand


async def test_the_range_summary_reads_its_own_gateway():
    module = RangeSummaryModule()
    module.gateway = gateway()
    summary = await module.handle(SummarizeRangeCommand(source="sample", offset_s=1.0, end_offset_s=2.0))
    assert summary.frames == 20 and summary.max_frequency_hz > 50.005
    for refused in (
        SummarizeRangeCommand(source="live", offset_s=0, end_offset_s=1),
        SummarizeRangeCommand(source="nope", offset_s=0, end_offset_s=1),
        SummarizeRangeCommand(source="sample", offset_s=2, end_offset_s=1),
    ):
        with pytest.raises(CommandRefused):
            module.validate(refused)
    with pytest.raises(CommandRefused, match="nothing"):
        await module.handle(SummarizeRangeCommand(source="sample", offset_s=10, end_offset_s=11))
