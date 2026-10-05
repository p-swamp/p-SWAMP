# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``ErrorEvent``: something in a pipeline failed.

A provider failed, a module's ``process`` raised, or a module refused a
command. Each is logged where it happens; the ``ErrorEvent`` is a copy on the
app's error topic, under the run's key, so the person using that run sees it.
It is not a grid alarm: an alarm is a module's normal result.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .data_model import DataModel

__all__ = ["ErrorEvent"]


class ErrorEvent(DataModel):
    """An operational failure in a pipeline."""

    version: Literal["v1"] = "v1"
    timestamp: datetime = Field(description="When the failure was seen.")
    source: str = Field(description="Who saw it: 'player', or a module's name.")
    message: str = Field(description="One line for a person: what failed.")
    detail: str | None = Field(default=None, description="The cause, e.g. 'Type: text' of an exception.")
    request_id: str | None = Field(default=None, description="The command this answers, if any.")
