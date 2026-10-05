# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``PmuFrame``: one instant of every channel in a stream, with its layout.

This is the shape p-SWAMP's applications consume (a labelled row per instant,
over a station / channel / measurement header) as a wire model.

**Every frame carries its layout** (``PmuFrame.header``). That repeats the
header at the frame rate (about 1.2x the bytes once a broker compresses a
batch), and in return any single frame is enough to work from: a module reads
the layout off the frame in hand, a late subscriber needs nothing else, and a
changed layout is just the next frame's header. ``header_id`` is a content
hash, so a consumer can tell cheaply whether the layout changed.

``values`` is ``float | None`` because NaN is not JSON: pydantic writes NaN as
``null``, and the type says so in the browser's contract.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from functools import cached_property
from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator

from .data_model import DataModel

__all__ = ["PmuFrame", "PmuHeader", "header_id_of"]


def header_id_of(
    station: list[str], channel: list[str], measurement: list[str], units: list[str], data_rate: float
) -> str:
    """A short content hash of a layout."""
    digest = hashlib.sha1()
    for row in (station, channel, measurement, units):
        digest.update("\x1f".join(row).encode())
        digest.update(b"\x1e")
    digest.update(repr(float(data_rate)).encode())
    return digest.hexdigest()[:12]


class PmuHeader(BaseModel):
    """The channel layout of a stream: one entry per column of a frame.

    The label rows are the ones p-SWAMP's ``Indexer`` queries, so
    ``columns(measurement="f")`` selects inputs the same way here.
    """

    station: list[str] = Field(description="Per column: the station (PMU) the value is from.")
    channel: list[str] = Field(description="Per column: the phasor or signal name.")
    measurement: list[str] = Field(
        description='Per column: "f", "df", "<name>_Magnitude" or "<name>_Angle".'
    )
    units: list[str] = Field(description="Per column: the unit of the value.")
    data_rate: float = Field(gt=0, description="Frames per second.")
    cimReferenceId: str | None = Field(
        default=None,
        description="The grid (CIM) data that applies to this layout. Set by the gateway, never by a provider.",
    )

    @model_validator(mode="after")
    def _rows_align(self) -> PmuHeader:
        if len({len(self.station), len(self.channel), len(self.measurement), len(self.units)}) != 1:
            raise ValueError("station, channel, measurement and units must be the same length")
        return self

    # Excludes cimReferenceId: the layout is the same with or without it.
    @computed_field(description="Content hash of the layout; equal layouts share it.")  # type: ignore[prop-decorator]
    @cached_property
    def header_id(self) -> str:
        return header_id_of(self.station, self.channel, self.measurement, self.units, self.data_rate)

    @property
    def n_columns(self) -> int:
        return len(self.station)

    @property
    def stations(self) -> list[str]:
        """The distinct stations, in column order."""
        return list(dict.fromkeys(self.station))

    def columns(
        self, *, station: str | None = None, channel: str | None = None, measurement: str | None = None
    ) -> list[int]:
        """The indexes of the columns matching every given label."""
        return [
            i
            for i in range(self.n_columns)
            if (station is None or self.station[i] == station)
            and (channel is None or self.channel[i] == channel)
            and (measurement is None or self.measurement[i] == measurement)
        ]


class PmuFrame(DataModel):
    """One instant of every channel in a stream."""

    version: Literal["v1"] = "v1"
    timestamp: datetime = Field(description="The PMU time of this instant.")
    mRID: str = Field(description="The stream (a PDC, a recording).")
    header: PmuHeader = Field(description="The channel layout; `values` follows its column order.")
    values: list[float | None] = Field(description="One value per header column; null where NaN.")

    @model_validator(mode="after")
    def _width_matches_header(self) -> PmuFrame:
        if len(self.values) != self.header.n_columns:
            raise ValueError(f"{len(self.values)} values for {self.header.n_columns} header columns")
        return self
