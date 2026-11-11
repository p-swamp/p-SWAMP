# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``CimEdits``: what a producer says the CIM graph should now hold.

The graph has one writer, the web backend's CIM graph app (ADR-014). Anyone
else who learns something the graph should know proposes it as a ``CimEdits``
message, and the writer applies the edits it allows that producer: the live
simulation reports a breaker it opened, and a topology-detection module will
report a line it found out of service (ADR-016).

An edit names a property as CIM does, ``<Class>.<attribute>`` (``Switch.open``,
``ACDCTerminal.connected``), the shape of LazyCIM's ``ChangeStatus.modified``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..common.data_model import DataModel

__all__ = ["CimEdit", "CimEdits"]


class CimEdit(BaseModel):
    """One property of one object, set to one value."""

    mRID: str = Field(description="The object whose property is set.")
    attribute: str = Field(
        pattern=r"^[A-Za-z]\w*\.[A-Za-z]\w*$",
        description="The property, as CIM names it: '<Class>.<attribute>', e.g. 'Switch.open'.",
    )
    # bool first, so that true stays a boolean rather than becoming 1.0.
    value: bool | float | str = Field(description="Its new value.")


class CimEdits(DataModel):
    """Edits a producer proposes, applied together or not at all."""

    version: Literal["v1"] = "v1"
    producer: str = Field(description="Who proposes them, e.g. 'rtsim': what the writer's allow-list is keyed by.")
    cause: str = Field(description="Why, in the producer's words: 'command', 'protection', ...")
    sim_time: float | None = Field(default=None, description="When it happened on a simulation's clock, s.")
    request_id: str | None = Field(default=None, description="The command they answer, if any.")
    edits: list[CimEdit] = Field(min_length=1)
