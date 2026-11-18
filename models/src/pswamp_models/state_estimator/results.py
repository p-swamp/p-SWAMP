"""``StateEstimatorResult``: the State Estimator module's result, one per frame."""

from typing import Literal

from pydantic import BaseModel, Field

from ..common import ResultEnvelope

__all__ = ["StateEstimatorBody", "StateEstimatorResult"]


class StateEstimatorBody(BaseModel):
    station: str = Field(description="The station with the highest frequency in the frame.")
    frequency_hz: float = Field(description="Its frequency, in Hz.")


class StateEstimatorResult(ResultEnvelope[StateEstimatorBody]):
    version: Literal["v1"] = "v1"
