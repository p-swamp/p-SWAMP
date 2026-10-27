"""``LineOutageResult``: the Line outage module's result, one per evaluation."""

from typing import Literal

from pydantic import BaseModel, Field

from ..common import AppStatus, ResultEnvelope

__all__ = ["LineOutageBody", "LineOutageChange", "LineOutageResult", "MeasuredCurrent"]


class MeasuredCurrent(BaseModel):
    """One current magnitude column of the stream: where it is measured."""

    station: str = Field(description="The station (PMU) it is measured at.")
    channel: str = Field(description="Its channel: the branch it measures, as the stream names it.")
    analog: str | None = Field(
        default=None,
        description="The CIM Analog it measures (the frame's PmuHeader.analog), when the stream says.",
    )


class LineOutageChange(BaseModel):
    kind: Literal["disconnect", "connect"] = Field(
        description="'disconnect': these currents fell below the threshold; 'connect': they came back."
    )
    currents: list[MeasuredCurrent]


class LineOutageBody(BaseModel):
    changes: list[LineOutageChange] = Field(
        description="What changed since the last evaluation; empty when nothing did."
    )
    disconnected: list[MeasuredCurrent] = Field(
        description="Every current carrying none now, whether it changed at this evaluation or before."
    )
    status: AppStatus = Field(description="'Alert' while any current carries none, 'OK' otherwise.")


class LineOutageResult(ResultEnvelope[LineOutageBody]):
    version: Literal["v1"] = "v1"
