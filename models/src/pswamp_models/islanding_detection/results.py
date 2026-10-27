"""``IslandingDetectionResult``: the Islanding module's result, one per evaluation."""

from typing import Literal

from pydantic import BaseModel, Field

from ..common import AppStatus, ResultEnvelope

__all__ = ["IslandingDetectionBody", "IslandingDetectionResult"]


class IslandingDetectionBody(BaseModel):
    islands: list[list[str]] = Field(
        description="The groups of stations separated from the main system, largest first, "
        "by station name; empty when the grid is whole."
    )
    status: AppStatus = Field(description="'Emergency' when there is an island, 'OK' when there is none.")


class IslandingDetectionResult(ResultEnvelope[IslandingDetectionBody]):
    version: Literal["v1"] = "v1"
