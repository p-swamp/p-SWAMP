# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``ExcursionResult`` (topic ``excursion.result``): is the mean frequency in its band."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..common.results import ResultEnvelope

__all__ = ["Excursion", "ExcursionResult"]


class Excursion(BaseModel):
    in_band: bool = Field(description="The mean frequency is within the band.")
    deviation_hz: float | None = Field(description="Mean frequency minus nominal.")
    band_hz: float = Field(description="How far from nominal still counts as in band.")
    excursions: int = Field(description="Excursions out of the band seen so far.")
    auto_pause: bool = Field(description="The player is paused when the frequency leaves the band.")


class ExcursionResult(ResultEnvelope[Excursion]):
    version: Literal["v1"] = "v1"
