# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``AlarmEvent``: a module's alarm was issued, or is no longer critical.

The desktop package's alarm message as a model. Every module that raises
alarms publishes this one class, so an alarm list reads one topic, as the
desktop's alarms topic is one for every application. ``AppStatus`` is the
status a module derives from its last assessment, which decides when it does.

An alarm's life here is its two module-side events, ``init`` and
``not_critical``, under one ``alarm_uuid``. What a person does with it
(acknowledge, silence, annotate) belongs to whatever keeps the alarm list,
not to the module.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .data_model import DataModel
from .results import AppIdentity

__all__ = ["AlarmEvent", "AppStatus"]

#: A module's status after its last assessment, as the desktop applications set it.
AppStatus = Literal["OK", "Alert", "Emergency"]


class AlarmEvent(DataModel):
    """One step in an alarm's life, as the module that raised it sees it."""

    version: Literal["v1"] = "v1"
    timestamp: datetime = Field(description="The assessment the event comes from, in message time.")
    alarm_uuid: str = Field(description="The alarm this event belongs to: every event of one alarm shares it.")
    app: AppIdentity = Field(description="The module instance that raised the alarm.")
    type: Literal["init", "not_critical"] = Field(
        description="'init' when the alarm is issued; 'not_critical' when its condition has cleared."
    )
    status: AppStatus = Field(description="The module's status when the event was raised.")
    message: str = Field(description="One line for a person.")
