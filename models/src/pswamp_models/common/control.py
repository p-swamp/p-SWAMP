# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``PipelineClosed``, a run's end; ``ModuleStarted``, a module instance's start."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .data_model import DataModel

__all__ = ["ModuleStarted", "PipelineClosed"]


class PipelineClosed(DataModel):
    """A run stopped (idle, evicted, shut down). Module hosts drop their
    instances for its key."""

    version: Literal["v1"] = "v1"
    timestamp: datetime
    reason: str = Field(default="stopped", description="idle, capacity or shutdown.")


class ModuleStarted(DataModel):
    """A module host started an instance for a run: its first, or a rebuilt
    one (after a worker restart, or a failure). The run sends it the sticky
    settings it has seen, which a rebuilt instance has lost."""

    version: Literal["v1"] = "v1"
    timestamp: datetime
    module: str = Field(description="The module's name.")
