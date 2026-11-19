"""``IslandingDetectionResult``: the Islanding module's result, one per evaluation.

The main system is not listed: in a large grid it is nearly every station, once a second, for no
news. It is every frequency station of the assessed layout (``header_id``) in no island and not
``unassigned``; ``main_stations`` works that out from the header.
"""

from typing import Literal

from pydantic import BaseModel, Field

from ..common import AppStatus, ResultEnvelope
from ..pmu import PmuHeader

__all__ = ["IslandGroup", "IslandingDetectionBody", "IslandingDetectionResult"]


class IslandGroup(BaseModel):
    stations: list[str] = Field(description="The group's stations, by name.")
    mean_freq: float | None = Field(
        description="Hz: the group's mean smoothed frequency over the assessed window."
    )


class IslandingDetectionBody(BaseModel):
    header_id: str = Field(description="The `PmuHeader.header_id` of the layout the assessment was made on.")
    islands: list[IslandGroup] = Field(
        description="The groups of stations separated from the main system, largest first; "
        "empty when the grid is whole."
    )
    main_mean_freq: float | None = Field(
        description="Hz: the main system's mean smoothed frequency over the assessed window; "
        "null when no station had a full window."
    )
    unassigned: list[str] = Field(
        description="Stations in no group: a missing or zero frequency somewhere in the window."
    )
    status: AppStatus = Field(description="'Emergency' when there is an island, 'OK' when there is none.")

    def main_stations(self, header: PmuHeader) -> list[str] | None:
        """The main system's stations, in ``header``'s order; ``None`` when ``header`` is not the
        layout this assessment was made on."""
        if header.header_id != self.header_id:
            return None
        excluded = {station for island in self.islands for station in island.stations} | set(self.unassigned)
        return [header.station[i] for i in header.columns(measurement="f") if header.station[i] not in excluded]


class IslandingDetectionResult(ResultEnvelope[IslandingDetectionBody]):
    version: Literal["v2"] = "v2"
