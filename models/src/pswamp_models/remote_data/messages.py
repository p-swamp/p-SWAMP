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
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from ..common.data_model import DataModel
from ..common.utc import ensure_utc

__all__ = ["RemoteDataQuery", "RemoteDataResult"]


class RemoteDataQuery(BaseModel):
    """A range query: records of ``model`` in ``[start, end)``; a null bound is open."""

    version: Literal["v1"] = "v1"
    query_id: str = Field(description="Client-generated, for matching the two sides' logs.")
    model: str = Field(description="The topic string of the records wanted, e.g. 'pmu.frame'.")
    start: datetime | None = Field(default=None, description="Inclusive start; null is open.")
    end: datetime | None = Field(default=None, description="Exclusive end; null is open.")

    @field_validator("start", "end")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)


class RemoteDataResult(BaseModel):
    """One line of a query's response: ``record``, ``end`` or ``error``."""

    kind: Literal["record", "end", "error"]
    model: str | None = Field(default=None, description="'record' only: the record's topic string.")
    record: dict[str, Any] | None = Field(default=None, description="'record' only: the record as JSON.")
    count: int | None = Field(default=None, ge=0, description="'end' only: records sent.")
    error: str | None = Field(default=None, description="'error' only: what went wrong.")

    @model_validator(mode="after")
    def _shape_matches_kind(self) -> RemoteDataResult:
        if self.kind == "record" and (self.model is None or self.record is None):
            raise ValueError("a 'record' line needs 'model' and 'record'")
        if self.kind == "end" and self.count is None:
            raise ValueError("an 'end' line needs 'count'")
        if self.kind == "error" and not self.error:
            raise ValueError("an 'error' line needs 'error'")
        return self

    @classmethod
    def for_record(cls, message: DataModel) -> RemoteDataResult:
        return cls(kind="record", model=type(message).topic, record=message.model_dump(mode="json"))

    def to_line(self) -> bytes:
        """One NDJSON line, newline included."""
        return self.model_dump_json(exclude_none=True).encode() + b"\n"
