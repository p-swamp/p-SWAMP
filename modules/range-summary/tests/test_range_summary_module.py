"""The range summary module: a batch query answered from the module's own gateway.

The gateway is built here, over two small in-memory sources (a recording and
a live feed), so the test needs nothing but the core and the models."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from pswamp_core.command_routing import CommandRefused
from pswamp_core.datagateway import DataClient, DataGateway, TimeRange
from pswamp_models.pmu import PmuFrame, PmuHeader
from pswamp_models.range_summary import RangeSummaryResult, SummarizeRangeCommand
from pswamp_modules.range_summary import RangeSummaryModule

RATE_HZ = 20.0
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
HEADER = PmuHeader(
    station=["A", "A", "B", "B"],
    channel=["V", "f", "V", "f"],
    measurement=["V_Magnitude", "f", "V_Magnitude", "f"],
    units=["kV", "Hz", "kV", "Hz"],
    data_rate=RATE_HZ,
)


def frame(t: float) -> PmuFrame:
    """A frame ``t`` s in: the frequency ramps up 4 mHz/s from 50 Hz."""
    f = 50.0 + 0.004 * t
    return PmuFrame(timestamp=T0 + timedelta(seconds=t), mRID="ramp", header=HEADER, values=[400.0, f, 400.0, f])


class Recording(DataClient):
    """Three seconds of the ramp, as a history."""

    kind = "history"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.frames = [frame(n / RATE_HZ) for n in range(int(3 * RATE_HZ))]

    async def coverage(self) -> TimeRange:
        return TimeRange(self.frames[0].timestamp, self.frames[-1].timestamp + timedelta(seconds=1 / RATE_HZ))

    async def consume(self, time_range: TimeRange):
        for record in self.frames:
            if time_range.contains(record.timestamp):
                yield record


class Feed(DataClient):
    """A live feed: the module refuses to summarize it."""

    kind = "live"

    async def consume(self, time_range: TimeRange):
        yield frame(0)


def gateway() -> DataGateway:
    return DataGateway([Recording("sample"), Feed("live")])


async def test_the_range_summary_reads_its_own_gateway():
    module = RangeSummaryModule()
    module.gateway = gateway()
    command = SummarizeRangeCommand(source="sample", offset_s=1.0, end_offset_s=2.0)
    (answer,) = await module.arun_command(command)
    assert isinstance(answer, RangeSummaryResult) and answer.request_id == command.request_id
    summary = answer.result
    assert summary.frames == 20 and summary.max_frequency_hz > 50.0075
    for refused in (
        SummarizeRangeCommand(source="live", offset_s=0, end_offset_s=1),
        SummarizeRangeCommand(source="nope", offset_s=0, end_offset_s=1),
        SummarizeRangeCommand(source="sample", offset_s=2, end_offset_s=1),
    ):
        with pytest.raises(CommandRefused):
            module.validate(refused)
    with pytest.raises(CommandRefused, match="nothing"):
        await module.ahandle(SummarizeRangeCommand(source="sample", offset_s=10, end_offset_s=11))


def test_the_range_summary_answers_from_plain_code():
    module = RangeSummaryModule()
    module.gateway = gateway()
    (answer,) = module.run_command(SummarizeRangeCommand(source="sample", offset_s=0.0, end_offset_s=1.0))
    assert answer.result.frames == 20
