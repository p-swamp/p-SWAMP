# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``ResultEnvelope``: what a module publishes.

A module subclasses the envelope with its own result body, and **that
subclass's name is its topic**::

    class FrameStats(BaseModel): ...
    class FrameStatsResult(ResultEnvelope[FrameStats]): ...   # topic frame.stats.result

This is the desktop package's ``{time_stamp, info, parameters, result}``
convention as a model.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

from .data_model import DataModel

__all__ = ["AppIdentity", "ResultEnvelope"]


class AppIdentity(BaseModel):
    """Which module instance produced a result."""

    name: str = Field(description="The module's name.")
    uuid: str = Field(description="This instance's id.")


T = TypeVar("T", bound=BaseModel)


class ResultEnvelope(DataModel, Generic[T]):
    """A module's result body, with where and when it came from."""

    version: Literal["v1"] = "v1"
    timestamp: datetime = Field(description="The instant the result is about.")
    app: AppIdentity
    parameters: dict[str, Any] = Field(default_factory=dict, description="The module's settings.")
    request_id: str | None = Field(default=None, description="Set when this result answers a command.")
    result: T
