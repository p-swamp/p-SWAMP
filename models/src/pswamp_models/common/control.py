# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``PipelineClosed``: a run's end."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .data_model import DataModel

__all__ = ["PipelineClosed"]


class PipelineClosed(DataModel):
    """A run stopped (idle, evicted, shut down). Module hosts drop their
    instances for its key."""

    version: Literal["v1"] = "v1"
    timestamp: datetime
    reason: str = Field(default="stopped", description="idle, capacity or shutdown.")
