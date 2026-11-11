# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``SimEvent``: something happened in the live simulation that a person should hear of."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from ..common.data_model import DataModel

__all__ = ["SimEvent"]


class SimEvent(DataModel):
    """A disturbance injected, or a protection operating: announced, never written to CIM."""

    version: Literal["v1"] = "v1"
    timestamp: datetime = Field(description="When it happened, wall clock.")
    mRID: str = Field(description="The CIM object it happened to.")
    kind: Literal[
        "open", "close", "trip", "reconnect", "short_circuit", "clear_short_circuit", "load_step", "reset"
    ] = Field(description="What happened.")
    cause: Literal["command", "disturbance", "protection"] = Field(description="Why.")
    sim_time: float = Field(description="When, on the simulation's clock, s.")
    detail: str | None = Field(default=None, description="One line for a person, e.g. 'overload 1.3 x limit'.")
    request_id: str | None = Field(default=None, description="The command it answers, if any.")
