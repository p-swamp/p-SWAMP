# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The two shapes of the remote data contract (doc/remote-data-integration-contract.md).

``RemoteDataQuery`` is what the client POSTs to ``/v1/queries``.
``RemoteDataResult`` is one NDJSON line of the streamed response: a ``record``
line per record, closed by exactly one ``end`` (or ``error``) line. The
response's status is sent before the first record, so the body is where a
failure part way, or the difference between "done" and "the connection
broke", is said.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
import math

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    TypeAdapter,
)

from ..common.utc import ensure_utc

__all__ = [
    "RemoteDataQuery",
    "RemoteDataResult",
    "ApiModel",
    "RecordResponse",
    "RecordMessage",
    "Phasor",
    "EndResponse",
    "EndMessage",
    "ErrorResponse",
    "ErrorMessage",
    "RESULT_ADAPTER",
]


class RemoteDataQuery(BaseModel):
    """A range query: records of ``model`` in ``[start, end)``; a null bound is
    open. With ``limit``, only the first ``limit`` of them: a page."""

    version : Literal["v1"] = "v1"
    stations: list[str] | None = Field(default=None, min_length=1, description="Non-empty list of station IDs; null is all stations")
    start   : datetime  | None = Field(default=None, description="Inclusive start; null is open.")
    end     : datetime  | None = Field(default=None, description="Exclusive end; null is open.")
    limit   : int       | None = Field(default=100000, ge=1, description="At most this many records, the first in the range; null is all.")

    @field_validator("start", "end")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
    )


class RemoteDataResult(ApiModel):
    """One line of a query's response: ``record``, ``end`` or ``error``."""
    mrid: str
    v: Literal["v1"]
    ts: datetime
    seq: int | None = None

    def to_line(self) -> bytes:
        """One NDJSON line, newline included."""
        return self.model_dump_json(exclude_none=True).encode() + b"\n"


class Phasor(ApiModel):
    name: str
    station: str
    kv: int
    phase: Literal["L1"] | Literal["L2"] | Literal["L3"]
    kind : Literal["I"]  | Literal["U"]
    bank : Literal["A"]  | Literal["B"]  | Literal["C"] | None = None
    magnitude: float
    angle: float
class RecordMessage(ApiModel):
    ts: datetime
    id: str
    name: str
    frequency: float
    rocof: float
    phasors: list[Phasor]
class RecordResponse(RemoteDataResult):
    kind: Literal["record"]
    msg: RecordMessage

    @staticmethod
    def test_record(
        request_id: str,
        ts: datetime,
        seq: int,
        station_id: str,
    ) -> RecordResponse:
        station_name = {
            "NO 12345": "NO 12345 stasion ABC1",
            "NO 54321": "NO 54321 stasjon CBA2",
        }[station_id]
        phasor_kv = 420
        phasor_station = {
            "NO 12345": "Ba1",
            "NO 54321": "Ab3",
        }[station_id]
        phasor_name = f"{phasor_kv}_{phasor_station}"
        station_offset = {
            "NO 12345": 0.0,
            "NO 54321": 17.0,
        }[station_id]
        return RecordResponse(
            mrid = request_id,
            v    = "v1",
            ts   = datetime.now(),
            seq  = seq,
            kind = "record",
            msg  = RecordMessage(
                ts = ts,
                id = station_id,
                name = station_name,
                frequency = _sine_at(ts, center=50.0, amplitude=0.1, period_seconds=60.0, phase=station_offset),
                rocof     = _sine_at(ts, center=0.0, amplitude=0.02, period_seconds=10.0, phase=station_offset),
                phasors = [
                    Phasor(
                        name = phasor_name + "_U_L1",
                        station = phasor_station,
                        kv = phasor_kv,
                        phase = "L1",
                        kind = "U",
                        magnitude = _sine_at(ts, center=240_000.0, amplitude=5_000.0, period_seconds=300.0, phase=0.0 + station_offset),
                        angle = _normalize_angle(-80.0 + _sine_at(ts, center=0.0, amplitude=2.0, period_seconds=600.0, phase=0.1 + station_offset)),
                    ),
                    Phasor(
                        name = phasor_name + "_U_L2",
                        station = phasor_station,
                        kv = phasor_kv,
                        phase = "L2",
                        kind = "U",
                        magnitude = _sine_at(ts, center=240_000.0, amplitude=5_000.0, period_seconds=300.0, phase=0.2 + station_offset),
                        angle = _normalize_angle(40.0 + _sine_at(ts, center=0.0, amplitude=2.0, period_seconds=600.0, phase=0.3 + station_offset)),
                    ),
                    Phasor(
                        name = phasor_name + "_U_L3",
                        station = phasor_station,
                        kv = phasor_kv,
                        phase = "L3",
                        kind = "U",
                        magnitude = _sine_at(ts, center=240_000.0, amplitude=5_000.0, period_seconds=300.0, phase=0.4 + station_offset),
                        angle = _normalize_angle(160.0 + _sine_at(ts, center=0.0, amplitude=2.0, period_seconds=600.0, phase=0.5 + station_offset)),
                    ),
                    Phasor(
                        name = phasor_name +"_I_L1",
                        station = phasor_station,
                        kv = phasor_kv,
                        phase = "L1",
                        kind = "I",
                        magnitude = _sine_at(ts, center=1.0, amplitude=0.2, period_seconds=45.0, phase=0.6 + station_offset),
                        angle = _normalize_angle(-80.0 + _sine_at(ts, center=0.0, amplitude=5.0, period_seconds=120.0, phase=0.7 + station_offset)),
                    ),
                    Phasor(
                        name = phasor_name + "_I_L2",
                        station = phasor_station,
                        kv = phasor_kv,
                        phase = "L2",
                        kind = "I",
                        magnitude = _sine_at(ts, center=1.0, amplitude=0.2, period_seconds=45.0, phase=0.8 + station_offset),
                        angle = _normalize_angle(40.0 + _sine_at(ts, center=0.0, amplitude=5.0, period_seconds=120.0, phase=0.9 + station_offset)),
                    ),
                    Phasor(
                        name = phasor_name + "_I_L3",
                        station = phasor_station,
                        kv = phasor_kv,
                        phase = "L3",
                        kind = "I",
                        magnitude = _sine_at(ts, center=1.0, amplitude=0.2, period_seconds=45.0, phase=1.0 + station_offset),
                        angle = _normalize_angle(160.0 + _sine_at(ts, center=0.0, amplitude=5.0, period_seconds=120.0, phase=1.1 + station_offset)),
                    ),
                ],
            ),
        )


class EndMessage(ApiModel):
    count: int
class EndResponse(RemoteDataResult):
    kind: Literal["end"]
    msg: EndMessage


class ErrorMessage(ApiModel):
    message: str
class ErrorResponse(RemoteDataResult):
    kind: Literal["error"]
    msg: ErrorMessage


def _sine_at(
    ts: datetime,
    center: float,
    amplitude: float,
    period_seconds: float,
    phase: float = 0.0,
) -> float:
    t = ts.timestamp()

    return center + amplitude * math.sin(
        2 * math.pi * t / period_seconds + phase
    )


def _normalize_angle(angle: float) -> float:
    return (angle + 180.0) % 360.0 - 180.0


RemoteDataLine = Annotated[RecordResponse | EndResponse | ErrorResponse, Field(discriminator="kind")]
RESULT_ADAPTER: TypeAdapter[RemoteDataLine] = TypeAdapter(RemoteDataLine)
